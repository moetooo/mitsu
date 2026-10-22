import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { 
      hasError: false, 
      error: null,
      errorInfo: null,
      showDetails: false
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error('[Mitsu ErrorBoundary caught error]:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null, showDetails: false });
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen w-full flex items-center justify-center p-6 bg-[var(--bg-color)] text-[var(--text-color)] select-none">
          <div className="max-w-md w-full bg-[var(--surface-color)] border border-[var(--border-color)] rounded-3xl p-8 sm:p-10 shadow-2xl text-center relative overflow-hidden backdrop-blur-md">
            
            {/* Subtle background ink ornament */}
            <span className="absolute -bottom-10 -right-10 text-9xl font-serif-jp opacity-[0.03] pointer-events-none select-none text-[var(--text-color)]">
              ❖
            </span>

            {/* Ink Crest Icon */}
            <div className="w-16 h-16 rounded-full bg-[var(--hanko-bg)] border border-[var(--hanko-border)] flex items-center justify-center mx-auto mb-6 shadow-inner animate-pulse">
              <span className="font-serif-jp text-2xl text-[var(--accent-vermillion)]">❖</span>
            </div>

            {/* Error Message */}
            <h1 className="text-xl sm:text-2xl font-bold font-serif-jp tracking-tight mb-2">
              Something went wrong
            </h1>
            <p className="text-xs font-mono text-[var(--accent-vermillion)] uppercase tracking-widest mb-4 opacity-90">
              予期せぬエラーが発生しました
            </p>
            <p className="text-sm text-[var(--text-muted)] font-light leading-relaxed mb-8">
              An unexpected interface error occurred. You can attempt to restore your session or reload the application.
            </p>

            {/* Action Buttons */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <button
                type="button"
                onClick={this.handleReload}
                className="w-full sm:w-auto px-6 py-2.5 rounded-full bg-[var(--accent-vermillion)] hover:opacity-90 text-white font-medium text-sm transition-all duration-200 shadow-md cursor-pointer active:scale-95"
              >
                Reload App
              </button>
              <button
                type="button"
                onClick={this.handleReset}
                className="w-full sm:w-auto px-5 py-2.5 rounded-full bg-[var(--surface-hover)] hover:bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] font-medium text-sm transition-all duration-200 cursor-pointer active:scale-95"
              >
                Try Again
              </button>
            </div>

            {/* Optional Diagnostics Toggle */}
            <div className="mt-8 pt-6 border-t border-[var(--border-color)]/60 text-center">
              <button
                type="button"
                onClick={() => this.setState(prev => ({ showDetails: !prev.showDetails }))}
                className="text-[11px] font-mono text-[var(--text-muted)] hover:text-[var(--text-color)] underline cursor-pointer"
              >
                {this.state.showDetails ? 'Hide Error Details' : 'Show Error Details'}
              </button>

              {this.state.showDetails && (
                <div className="mt-3 text-left p-3.5 rounded-xl bg-black/40 border border-[var(--border-color)] max-h-44 overflow-y-auto font-mono text-[11px] text-red-400 select-text leading-snug break-all">
                  <p className="font-bold mb-1">{this.state.error?.toString()}</p>
                  {this.state.errorInfo?.componentStack && (
                    <pre className="text-[10px] text-neutral-400 whitespace-pre-wrap">
                      {this.state.errorInfo.componentStack}
                    </pre>
                  )}
                </div>
              )}
            </div>

          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
