import { vi } from 'vitest'

Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
})

class EventSourceStub {
  onerror: ((event: Event) => void) | null = null

  constructor(public readonly url: string) {}

  addEventListener() {}

  close() {}
}

vi.stubGlobal('EventSource', EventSourceStub)
