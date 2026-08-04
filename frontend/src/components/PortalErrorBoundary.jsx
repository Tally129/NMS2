import React from "react";
import { AlertTriangle, Home, RefreshCw } from "lucide-react";
import { Button } from "./ui/button";

export default class PortalErrorBoundary extends React.Component {
  constructor(props) {
    super(props);

    this.state = {
      hasError: false,
      error: null,
      resetKey: 0,
    };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error, info) {
    console.error("Portal page rendering error", {
      message: error?.message,
      stack: error?.stack,
      componentStack: info?.componentStack,
      pathname: window.location.pathname,
    });
  }

  componentDidUpdate(previousProps) {
    // Reset automatically when navigation changes.
    if (
      previousProps.locationKey !== this.props.locationKey &&
      this.state.hasError
    ) {
      this.setState({
        hasError: false,
        error: null,
      });
    }
  }

  resetBoundary = () => {
    this.setState((current) => ({
      hasError: false,
      error: null,
      resetKey: current.resetKey + 1,
    }));
  };

  render() {
    if (!this.state.hasError) {
      return (
        <React.Fragment key={this.state.resetKey}>
          {this.props.children}
        </React.Fragment>
      );
    }

    return (
      <div className="mx-auto my-10 max-w-xl rounded-2xl border border-[#d9a6a6] bg-[#fff7f7] p-8 text-center shadow-sm">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#f4dede]">
          <AlertTriangle
            size={28}
            className="text-[#8a3535]"
          />
        </div>

        <h2 className="mt-4 font-display text-2xl text-[#1f2a22]">
          This section could not be displayed
        </h2>

        <p className="mt-2 text-sm leading-6 text-[#6a6a6a]">
          The rest of your portal and session are still available.
          Try loading this section again or return to the dashboard.
        </p>

        {process.env.NODE_ENV !== "production" &&
          this.state.error?.message && (
            <pre className="mt-4 max-h-40 overflow-auto rounded-xl bg-white p-3 text-left text-xs text-[#7a2a2a]">
              {this.state.error.message}
            </pre>
          )}

        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={this.resetBoundary}
            className="rounded-full"
          >
            Try again
          </Button>

          <Button
            type="button"
            variant="outline"
            onClick={() => {
              window.location.href = "/portal/admin/dashboard";
            }}
            className="rounded-full"
          >
            <Home size={14} className="mr-2" />
            Dashboard
          </Button>

          <Button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-full bg-[#2f4a3a] text-[#f6f1e6] hover:bg-[#263d30]"
          >
            <RefreshCw size={14} className="mr-2" />
            Refresh page
          </Button>
        </div>
      </div>
    );
  }
}
