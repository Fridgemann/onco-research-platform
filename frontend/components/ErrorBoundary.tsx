'use client'

import { Component, ReactNode } from 'react'

type Props = { children: ReactNode; fallback?: ReactNode }
type State = { error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return this.props.fallback ?? (
        <div className="alert-error" style={{ fontSize: '12px' }}>
          Failed to render result. The data returned by the server may be malformed.
        </div>
      )
    }
    return this.props.children
  }
}
