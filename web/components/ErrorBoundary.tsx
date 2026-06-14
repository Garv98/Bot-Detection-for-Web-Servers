"use client";

import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/** Catches render errors and shows a styled fallback instead of a blank screen. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 32 }}>
          <div className="card" style={{ padding: 24, borderLeft: "3px solid var(--bot)", maxWidth: 560 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 8px", color: "var(--bot)" }}>Something went wrong</h2>
            <p style={{ fontSize: 14, color: "var(--muted)", margin: "0 0 14px" }}>
              A rendering error occurred on this page. The rest of the app is unaffected.
            </p>
            <pre className="mono" style={{ fontSize: 12, color: "var(--muted-2)", whiteSpace: "pre-wrap", margin: "0 0 16px" }}>
              {this.state.error.message}
            </pre>
            <button onClick={this.reset}
              style={{ padding: "9px 16px", background: "var(--accent)", color: "var(--on-accent)", border: "none", borderRadius: 10, fontWeight: 600, fontSize: 13 }}>
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
