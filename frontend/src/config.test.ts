import { describe, expect, it } from 'vitest'

import { getApiBaseUrl } from './config'

describe('getApiBaseUrl', () => {
  it('builds the API base URL from the configured backend URL', () => {
    expect(getApiBaseUrl({ backendUrl: 'https://backend.example.com/' })).toBe('https://backend.example.com/api')
  })

  it('does not duplicate /api when backendUrl already includes it', () => {
    expect(getApiBaseUrl({ backendUrl: 'https://backend.example.com/api/' })).toBe('https://backend.example.com/api')
  })

  it('allows an explicit apiBaseUrl override', () => {
    expect(getApiBaseUrl({ apiBaseUrl: 'https://backend.example.com/custom-api/' })).toBe(
      'https://backend.example.com/custom-api',
    )
  })
})
