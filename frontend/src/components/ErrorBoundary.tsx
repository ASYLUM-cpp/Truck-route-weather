import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error in component:', error, errorInfo);
  }

  public render() {
    if (this.state.error) {
      const msg = this.state.error.message || '';
      const isWebGL = msg.includes('WebGL') || msg.includes('webgl');
      return (
        <div
          role="alert"
          style={{
            padding: '2rem',
            margin: '2rem auto',
            maxWidth: '600px',
            background: '#ffffff',
            borderRadius: '8px',
            border: '1px solid #fee2e2',
            boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
            fontFamily: 'system-ui, sans-serif',
          }}
        >
          <h2 style={{ color: '#991b1b', marginTop: 0 }}>
            {isWebGL ? 'WebGL Hardware Acceleration Required' : 'Something went wrong'}
          </h2>
          <p style={{ color: '#374151', lineHeight: 1.5 }}>
            {isWebGL
              ? 'The interactive route map requires WebGL, which is currently disabled or unavailable in this browser window.'
              : this.state.error.message}
          </p>
          {isWebGL && (
            <div
              style={{
                background: '#f9fafb',
                padding: '1rem',
                borderRadius: '6px',
                fontSize: '0.875rem',
                color: '#4b5563',
              }}
            >
              <strong>How to enable:</strong>
              <ol style={{ paddingLeft: '1.25rem', marginTop: '0.5rem', marginBottom: 0 }}>
                <li>
                  Open your browser settings (e.g. <code>chrome://settings/system</code>).
                </li>
                <li>
                  Turn on <strong>"Use graphics acceleration when available"</strong> (or "Use hardware acceleration").
                </li>
                <li>Restart your browser and refresh this page.</li>
              </ol>
            </div>
          )}
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '1.5rem',
              padding: '0.5rem 1rem',
              background: '#2563eb',
              color: '#ffffff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Refresh Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
