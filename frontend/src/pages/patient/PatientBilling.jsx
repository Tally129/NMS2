import React from "react";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  ExpressCheckoutElement,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import PortalLayout, {
  PortalHeader,
} from "../PortalLayout";
import api, { downloadBlob } from "../../lib/api";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";

import {
  Receipt,
  CheckCircle2,
  AlertCircle,
  Eye,
  Download,
} from "lucide-react";
import {
  normalizeArray,
} from "../../lib/collections";


const money = (value) =>
  Number(value || 0).toLocaleString(
    "en-US",
    {
      style: "currency",
      currency: "USD",
    }
  );

const formatDate = (value) =>
  value
    ? new Date(value).toLocaleDateString(
        [],
        {
          month: "short",
          day: "numeric",
          year: "numeric",
        }
      )
    : "—";

const transactionNumber = (txn) => {
  const created = txn.created_at
    ? new Date(txn.created_at)
    : new Date();

  const year = created.getFullYear();
  const month = String(
    created.getMonth() + 1
  ).padStart(2, "0");
  const day = String(
    created.getDate()
  ).padStart(2, "0");

  return `INV-${year}${month}${day}-${String(
    txn.id || ""
  )
    .slice(0, 6)
    .toUpperCase()}`;
};



function StripeElementsProvider({
  publishableKey,
  clientSecret,
  children,
}) {
  const stripePromise = React.useMemo(
    () => loadStripe(publishableKey),
    [publishableKey]
  );

  const options = React.useMemo(
    () => ({
      clientSecret,
      appearance: {
        theme: "stripe",
      },
    }),
    [clientSecret]
  );

  return (
    <Elements
      stripe={stripePromise}
      options={options}
    >
      {children}
    </Elements>
  );
}


function StripeInvoiceCheckout({
  invoice,
  onComplete,
}) {
  const stripe = useStripe();
  const elements = useElements();

  const [submitting, setSubmitting] =
    React.useState(false);

  const [errorMessage, setErrorMessage] =
    React.useState("");

  const handleConfirmationResult = (result) => {
    if (result?.error) {
      setErrorMessage(
        result.error.message ||
          "Payment could not be completed."
      );
      return false;
    }

    const status =
      result?.paymentIntent?.status || "";

    if (
      status === "succeeded" ||
      status === "processing" ||
      status === "requires_capture"
    ) {
      onComplete?.(status);
      return true;
    }

    setErrorMessage(
      "Payment confirmation is still pending. " +
        "Your invoice will update after Stripe confirms payment."
    );

    return false;
  };

  const submitPayment = async (event) => {
    event.preventDefault();

    if (!stripe || !elements || submitting) {
      return;
    }

    setSubmitting(true);
    setErrorMessage("");

    try {
      const result = await stripe.confirmPayment({
        elements,
        confirmParams: {
          return_url: (
            `${window.location.origin}/portal/patient/billing`
          ),
        },
        redirect: "if_required",
      });

      handleConfirmationResult(result);
    } catch (error) {
      setErrorMessage(
        error?.message ||
          "Payment could not be completed."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const submitExpressPayment = async () => {
    if (!stripe || !elements || submitting) {
      return;
    }

    setSubmitting(true);
    setErrorMessage("");

    try {
      const result = await stripe.confirmPayment({
        elements,
        confirmParams: {
          return_url: (
            `${window.location.origin}/portal/patient/billing`
          ),
        },
        redirect: "if_required",
      });

      handleConfirmationResult(result);
    } catch (error) {
      setErrorMessage(
        error?.message ||
          "Wallet payment could not be completed."
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={submitPayment}
      className="space-y-4"
    >
      <div className="space-y-3">
        <ExpressCheckoutElement
          onConfirm={submitExpressPayment}
          options={{
            buttonType: {
              applePay: "buy",
              googlePay: "buy",
            },
          }}
        />

        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">
            or pay another way
          </span>
          <div className="h-px flex-1 bg-border" />
        </div>

        <PaymentElement />
      </div>

      {errorMessage && (
        <div
          className="rounded-xl border p-3 text-sm"
          role="alert"
        >
          {errorMessage}
        </div>
      )}

      <Button
        type="submit"
        className="w-full rounded-xl"
        disabled={!stripe || !elements || submitting}
      >
        {submitting
          ? "Processing…"
          : `Pay ${money(invoice?.amount || 0)}`}
      </Button>

      <div className="text-xs text-muted-foreground">
        Payment information is entered directly into
        Stripe's secure payment fields. Natural Medical
        Solutions does not receive or store your full
        card number or security code.
      </div>
    </form>
  );
}

export default function PatientBilling() {

  const [paymentInvoice, setPaymentInvoice] =
    React.useState(null);

  const [stripeCheckout, setStripeCheckout] =
    React.useState(null);

  const [stripeCheckoutLoading, setStripeCheckoutLoading] =
    React.useState(false);

  const [stripeCheckoutError, setStripeCheckoutError] =
    React.useState("");

  const [paymentConfig, setPaymentConfig] =
    React.useState(null);

  const [paymentConfigLoading, setPaymentConfigLoading] =
    React.useState(false);

  const [paymentConfigError, setPaymentConfigError] =
    React.useState("");

  const loadPaymentConfig = React.useCallback(
    async () => {
      setPaymentConfigLoading(true);
      setPaymentConfigError("");

      try {
        const response = await api.get(
          "/payments/config"
        );

        setPaymentConfig(response.data || {});
      } catch (error) {
        setPaymentConfig(null);

        setPaymentConfigError(
          error?.response?.data?.detail?.message ||
          error?.response?.data?.detail ||
          error?.message ||
          "Payment options could not be loaded."
        );
      } finally {
        setPaymentConfigLoading(false);
      }
    },
    []
  );

  const openPayment = async (invoice) => {
    setPaymentInvoice(invoice);
    setStripeCheckout(null);
    setStripeCheckoutError("");
    await loadPaymentConfig();
  };

  const closePayment = () => {
    setPaymentInvoice(null);
    setPaymentConfigError("");
    setStripeCheckout(null);
    setStripeCheckoutError("");
    setStripeCheckoutLoading(false);
  };

  const beginStripeCheckout = async () => {
    if (!paymentInvoice?.id || stripeCheckoutLoading) {
      return;
    }

    setStripeCheckoutLoading(true);
    setStripeCheckoutError("");

    try {
      const response = await api.post(
        `/invoices/${paymentInvoice.id}/stripe-intent`
      );

      const data = response.data || {};

      if (
        !data.client_secret ||
        !data.publishable_key
      ) {
        throw new Error(
          "Stripe checkout configuration is incomplete."
        );
      }

      setStripeCheckout({
        clientSecret: data.client_secret,
        publishableKey: data.publishable_key,
      });
    } catch (error) {
      setStripeCheckout(null);

      setStripeCheckoutError(
        error?.response?.data?.detail?.message ||
          error?.response?.data?.detail ||
          error?.message ||
          "Secure card checkout is not available yet."
      );
    } finally {
      setStripeCheckoutLoading(false);
    }
  };

  const [transactions, setTransactions] =
    React.useState([]);
  const [legacyInvoices, setLegacyInvoices] =
    React.useState([]);
  const [tab, setTab] =
    React.useState("unpaid");
  const [loading, setLoading] =
    React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);

    try {
      const [
        transactionResponse,
        invoiceResponse,
      ] = await Promise.all([
        api.get(
          "/transactions?limit=500"
        ),
        api.get("/invoices"),
      ]);

      setTransactions(
        normalizeArray(
          transactionResponse.data,
          ["rows", "items"]
        )
      );

      setLegacyInvoices(
        normalizeArray(
          invoiceResponse.data,
          ["items"]
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const transactionItems =
    normalizeArray(transactions).map(
      (txn) => ({
        id: txn.id,
        source: "transaction",
        invoiceNumber:
          transactionNumber(txn),
        amount: txn.total,
        status:
          txn.status === "paid"
            ? "paid"
            : "due",
        created_at: txn.created_at,
        paid_at: txn.paid_at,
        payment_method:
          txn.payment_method,
        unread: Boolean(
          txn.patient_unread
        ),
        description:
          normalizeArray(
            txn.lines
          )
            .map((line) => line.name)
            .filter(Boolean)
            .join(", ") ||
          "Patient invoice",
        raw: txn,
      })
    );

  const membershipItems =
    normalizeArray(legacyInvoices).map(
      (invoice) => ({
        id: invoice.id,
        source: "invoice",
        invoiceNumber: `INV-${String(
          invoice.id || ""
        )
          .slice(0, 8)
          .toUpperCase()}`,
        amount: invoice.amount,
        status: invoice.status,
        created_at:
          invoice.created_at,
        paid_at: invoice.paid_at,
        payment_method:
          invoice.payment_method,
        description:
          invoice.description ||
          "Invoice",
        raw: invoice,
      })
    );

  const allItems = [
    ...transactionItems,
    ...membershipItems,
  ].sort(
    (a, b) =>
      new Date(b.created_at || 0) -
      new Date(a.created_at || 0)
  );

  const unpaid = allItems.filter(
    (item) => item.status !== "paid"
  );

  const paid = allItems.filter(
    (item) => item.status === "paid"
  );

  const visible =
    tab === "paid" ? paid : unpaid;

  const openTransactionInvoice =
    async (item) => {
      try {
        await api.post(
          `/transactions/${item.id}/view`
        );

        setTransactions((current) =>
          normalizeArray(current).map(
            (txn) =>
              txn.id === item.id
                ? {
                    ...txn,
                    patient_unread:
                      false,
                  }
                : txn
          )
        );

        window.dispatchEvent(
          new CustomEvent(
            "nms:billing-viewed"
          )
        );
      } catch {
        // Viewing the PDF must remain
        // available if read tracking fails.
      }

      await downloadBlob(
        `/transactions/${item.id}/receipt`,
        {
          filename: `${item.invoiceNumber}.pdf`,
        }
      );
    };

  const openLegacyInvoice =
    async (item) => {
      try {
        await api.post(
          `/invoices/${item.id}/view`
        );

        window.dispatchEvent(
          new CustomEvent(
            "nms:billing-viewed"
          )
        );
      } catch {
        // Do not block the invoice
        // experience on read tracking.
      }

      // Legacy membership invoices do
      // not currently have a PDF route.
      window.alert(
        `${item.invoiceNumber}\n\n` +
          `${item.description}\n` +
          `${money(item.amount)}\n` +
          `${
            item.status === "paid"
              ? "Paid"
              : "Payment due"
          }`
      );
    };

  const openItem = (item) => {
    if (
      item.source === "transaction"
    ) {
      return openTransactionInvoice(
        item
      );
    }

    return openLegacyInvoice(item);
  };

  return (
    <>
    <PortalLayout>
      <PortalHeader
        title="Billing"
        subtitle="View invoices, payment status, and receipts."
      />

      <div className="flex flex-wrap gap-2 mb-6">
        <button
          type="button"
          onClick={() =>
            setTab("unpaid")
          }
          className={`px-4 py-2 rounded-full text-sm font-medium ${
            tab === "unpaid"
              ? "bg-[#2f4a3a] text-[#f6f1e6]"
              : "bg-[#f1ead8] text-[#5d513d]"
          }`}
        >
          Unpaid
          {unpaid.length > 0 && (
            <span className="ml-2">
              {unpaid.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() =>
            setTab("paid")
          }
          className={`px-4 py-2 rounded-full text-sm font-medium ${
            tab === "paid"
              ? "bg-[#2f4a3a] text-[#f6f1e6]"
              : "bg-[#f1ead8] text-[#5d513d]"
          }`}
        >
          Paid
          {paid.length > 0 && (
            <span className="ml-2">
              {paid.length}
            </span>
          )}
        </button>
      </div>

      {loading ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center">
          Loading billing…
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <Receipt
            size={30}
            className="mx-auto text-[#c19a4b]"
          />

          <div className="mt-3">
            {tab === "paid"
              ? "No paid invoices yet."
              : "You have no unpaid invoices."}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {visible.map((item) => (
            <React.Fragment
              key={`${item.source}-${item.id}`}
            >
            <button
              type="button"
              onClick={() =>
                openItem(item)
              }
              className="w-full text-left rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-5 hover:bg-[#f8f1e2] transition"
            >
              <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                <div className="relative w-11 h-11 rounded-xl bg-[#f1ead8] flex items-center justify-center shrink-0">
                  <Receipt
                    size={20}
                    className="text-[#8a6a3c]"
                  />

                  {item.unread && (
                    <span
                      className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-[#c19a4b]"
                      title="New invoice"
                    />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="font-medium text-[#2f342f]">
                    {item.description}
                  </div>

                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#6a6a6a]">
                    <span>
                      {item.invoiceNumber}
                    </span>

                    <span>
                      {formatDate(
                        item.created_at
                      )}
                    </span>
                  </div>
                </div>

                <div className="sm:text-right">
                  <div className="font-semibold text-[#2f342f]">
                    {money(item.amount)}
                  </div>

                  <div
                    className={`mt-1 inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full ${
                      item.status ===
                      "paid"
                        ? "bg-[#e7dfc9] text-[#2f4a3a]"
                        : "bg-[#fbf2d9] text-[#6b4a1c]"
                    }`}
                  >
                    {item.status ===
                    "paid" ? (
                      <CheckCircle2
                        size={12}
                      />
                    ) : (
                      <AlertCircle
                        size={12}
                      />
                    )}

                    {item.status ===
                    "paid"
                      ? "Paid"
                      : "Payment due"}
                  </div>
                </div>

                <div className="inline-flex items-center gap-1 text-xs font-medium text-[#8a6a3c]">
                  {item.source ===
                  "transaction" ? (
                    <>
                      <Download
                        size={14}
                      />
                      View PDF
                    </>
                  ) : (
                    <>
                      <Eye size={14} />
                      View invoice
                    </>
                  )}
                </div>
              </div>
            </button>

            {item.source === "invoice" &&
              item.status !== "paid" && (
                <div className="flex justify-end -mt-1 mb-2">
                  <Button
                    type="button"
                    onClick={() => openPayment(item)}
                    className="rounded-xl"
                  >
                    Pay invoice
                  </Button>
                </div>
              )}

            </React.Fragment>

          ))}
        </div>
      )}
    </PortalLayout>

      <Dialog
        open={Boolean(paymentInvoice)}
        onOpenChange={(open) => {
          if (!open) closePayment();
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              Pay invoice
            </DialogTitle>

            <DialogDescription>
              Choose how you would like to pay.
              Payment methods become available after
              merchant account setup is completed.
            </DialogDescription>
          </DialogHeader>

          {paymentInvoice && (
            <div className="space-y-5">
              <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-4">
                <div className="text-sm text-muted-foreground">
                  Amount due
                </div>

                <div className="text-2xl font-semibold mt-1">
                  {new Intl.NumberFormat(
                    "en-US",
                    {
                      style: "currency",
                      currency: "USD",
                    }
                  ).format(
                    Number(
                      paymentInvoice.amount || 0
                    )
                  )}
                </div>
              </div>

              {paymentConfigLoading ? (
                <div className="py-6 text-sm text-muted-foreground">
                  Loading payment options…
                </div>
              ) : paymentConfigError ? (
                <div
                  className="rounded-xl border p-4 text-sm"
                  role="alert"
                >
                  {paymentConfigError}
                </div>
              ) : (
                <div className="space-y-3">

                  <div className="rounded-2xl border p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="font-medium">
                          Secure card
                        </div>

                        <div className="text-sm text-muted-foreground mt-1">
                          Pay securely with a debit or
                          credit card through Stripe.
                        </div>
                      </div>

                      <span className="text-xs rounded-full border px-2.5 py-1 whitespace-nowrap">
                        {paymentConfig?.stripe?.enabled
                          ? "Available"
                          : "Setup required"}
                      </span>
                    </div>

                    {!stripeCheckout ? (
                      <>
                        <div className="text-xs text-muted-foreground mt-3">
                          Card numbers and security codes
                          are entered directly into Stripe's
                          secure payment fields. Natural
                          Medical Solutions does not store
                          the full card number or CVV.
                        </div>

                        {stripeCheckoutError && (
                          <div
                            className="rounded-xl border p-3 text-sm mt-3"
                            role="alert"
                          >
                            {stripeCheckoutError}
                          </div>
                        )}

                        <Button
                          type="button"
                          variant="outline"
                          className="w-full mt-4"
                          disabled={
                            !paymentConfig?.stripe?.enabled ||
                            stripeCheckoutLoading
                          }
                          onClick={beginStripeCheckout}
                        >
                          {stripeCheckoutLoading
                            ? "Preparing secure checkout…"
                            : "Pay with card"}
                        </Button>
                      </>
                    ) : (
                      <div className="mt-4">
                        <StripeElementsProvider
                          publishableKey={
                            stripeCheckout.publishableKey
                          }
                          clientSecret={
                            stripeCheckout.clientSecret
                          }
                        >
                          <StripeInvoiceCheckout
                            invoice={paymentInvoice}
                            onComplete={() => {
                              setStripeCheckout(null);
                              closePayment();

                              window.setTimeout(() => {
                                load();
                              }, 1200);
                            }}
                          />
                        </StripeElementsProvider>
                      </div>
                    )}
                  </div>


                  <div className="rounded-2xl border p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="font-medium">
                          PayPal
                        </div>

                        <div className="text-sm text-muted-foreground mt-1">
                          Pay using your PayPal account.
                        </div>
                      </div>

                      <span className="text-xs rounded-full border px-2.5 py-1 whitespace-nowrap">
                        {paymentConfig?.paypal?.enabled
                          ? "Available"
                          : "Setup required"}
                      </span>
                    </div>

                    <Button
                      type="button"
                      variant="outline"
                      className="w-full mt-4"
                      disabled
                    >
                      Pay with PayPal
                    </Button>
                  </div>


                  <div className="rounded-2xl border p-4">
                    <div className="font-medium">
                      Apple Pay & Google Pay
                    </div>

                    <div className="text-sm text-muted-foreground mt-1">
                      Eligible wallets are shown automatically
                      inside Stripe secure checkout after you
                      select Pay with card.
                    </div>
                  </div>

                </div>
              )}

              <div className="text-xs text-muted-foreground">
                Chase POS is available for in-person
                checkout only and is intentionally not
                offered as an online payment method.
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

    </>
  );
}
