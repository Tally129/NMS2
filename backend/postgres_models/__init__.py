"""Barrel exports so Alembic and repositories import from one place."""
from .base import Base  # noqa: F401
from .user import User, Client  # noqa: F401
from .user_session import UserSession  # noqa: F401
from .refresh_token import RefreshToken  # noqa: F401
from .login import LoginHistory, LoginContinuation  # noqa: F401
from .password_reset import PasswordResetAttempt, PasswordResetToken  # noqa: F401
from .audit import AuditLog, SecurityEvent  # noqa: F401
from .recovery_code import RecoveryCode  # noqa: F401
from .patient_profile import (  # noqa: F401
    IntakeForm,
    SupplementSheet,
    ClientSupplementAssignment,
    LegacyPasswordResetToken,
)
from .scheduling import (  # noqa: F401
    Appointment,
    AppointmentRequest,
    Availability,
    Reminder,
    ReminderSettings,
)
from .clinical_and_messaging import (  # noqa: F401
    VisitNote, TreatmentPlan, Treatment, LabValue, LiveSoapDraft, VisitChat,
    ClinicalDelegation,
    MessageThread, Message, FormTemplate, FormSubmission, SoapTemplate,
    PushSubscription,
)
from .crm_and_ops import (  # noqa: F401
    Campaign, FrontDeskVisit, InternalTask, IntegrationLog,
    ProtocolEnrollment, ProtocolTemplate, FileMeta,
)
from .structured_rest import (  # noqa: F401
    ChartOfAccount, JournalEntry, TransactionRow, Expense, Invoice,
    VendorBill, Vendor, AccountingBackfillRun, AccountingEvent,
    BankAccount, BankImportBatch, BankTransaction, BankTransfer,
    ImportedBatch, Reconciliation,
    Employee, PayrollRun, TimeEntry,
    InventoryItem, InventoryTransaction,
    BaaRecord, LegalAcceptance, LegalPolicy,
    BreakglassSession,
    PostingDeadLetter, VipListEntry, WsTicket, UserSessionCompat,
    Membership, CampaignTemplate, CampaignUnsubscribe, LegacyForm, SymptomLog,
)

from .payment_methods import (  # noqa: F401
    PaymentCustomer, SavedPaymentMethod,
)

from postgres_models.terminals import PaymentTerminal, TerminalPaymentAttempt

# Marketing OS PostgreSQL models.
# Imported here so SQLAlchemy metadata registers the Marketing OS tables.
from .marketing_os import (  # noqa: F401
    MarketingGoal,
    MarketingBudget,
    MarketingChannelAccount,
    MarketingDailyMetric,
    MarketingConversionEvent,
    MarketingAttribution,
    MarketingRecommendation,
    MarketingApproval,
    MarketingAction,
)

# Marketing OS Search Intelligence PostgreSQL models.
from .marketing_search import (  # noqa: F401
    MarketingSearchSite,
    MarketingSearchKeyword,
    MarketingKeywordRankSnapshot,
    MarketingSiteAuditRun,
    MarketingSiteAuditIssue,
)

# Marketing OS Google Search Console (read-only) PostgreSQL models.
from .marketing_gsc import (  # noqa: F401
    MarketingGscSyncRun,
    MarketingGscDailyMetric,
    MarketingGscQueryMetric,
    MarketingGscPageMetric,
)

# Marketing OS Phase 3 (competitors / keyword gap / backlinks / local).
from .marketing_phase3 import (  # noqa: F401
    MarketingSearchCompetitor,
    MarketingKeywordGapSnapshot,
    MarketingBacklinkSnapshot,
    MarketingLocalRankSnapshot,
)

from .marketing_leads import (  # noqa: F401
    MarketingLead,
    MarketingLeadTask,
    MarketingLeadAssignment,
    MarketingLeadActivity,
)

# Marketing OS Phase 7 — funnels / qualification / offers.
from .marketing_phase7 import (  # noqa: F401
    MarketingOffer,
    MarketingQualificationForm,
    MarketingFunnel,
    MarketingFunnelStep,
    MarketingQualificationSubmission,
)
from .marketing_phase8 import (  # noqa: F401
    MarketingNurtureSequence,
    MarketingNurtureStep,
    MarketingNurtureEnrollment,
    MarketingNurtureAction,
)
from .marketing_phase9 import (  # noqa: F401
    MarketingExperiment,
    MarketingExperimentVariant,
    MarketingExperimentAssignment,
    MarketingExperimentOutcome,
)
from .marketing_phase10 import (  # noqa: F401
    MarketingLocation,
    MarketingReputationSource,
    MarketingReputationSnapshot,
    MarketingLocalListingSnapshot,
    MarketingLocalOpportunity,
)
from .marketing_phase11 import (  # noqa: F401
    MarketingContentTopic,
    MarketingContentBrief,
    MarketingContentDraft,
    MarketingSocialPlan,
    MarketingContentCalendarItem,
)

