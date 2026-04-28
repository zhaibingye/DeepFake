import { describe, expect, it } from 'vitest'

import { formatApiErrorDetail } from './api'

describe('formatApiErrorDetail', () => {
  it('renders FastAPI validation arrays into readable lines', () => {
    expect(
      formatApiErrorDetail([
        {
          loc: ['body', 'api_url'],
          msg: 'String should have at least 1 character',
          type: 'string_too_short',
        },
        {
          loc: ['body', 'api_key'],
          msg: 'String should have at least 1 character',
          type: 'string_too_short',
        },
      ]),
    ).toBe(
      'api_url: String should have at least 1 character\napi_key: String should have at least 1 character',
    )
  })

  it('falls back to stringifying non-standard objects', () => {
    expect(formatApiErrorDetail({ detail: 'bad request' })).toBe('{"detail":"bad request"}')
  })
})
