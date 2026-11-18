import { apiFetch } from '../../src/lib/api';

describe('apiFetch', () => {
  beforeEach(() => {
    global.fetch = jest.fn(() => Promise.resolve({ ok: true })) as unknown as jest.Mock;
  });

  it('sends JSON bodies as JSON', async () => {
    await apiFetch('/x', { method: 'POST', body: JSON.stringify({ a: 1 }) });

    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.headers['Content-Type']).toBe('application/json');
  });

  it('leaves the content type of a file upload to the browser', async () => {
    const form = new FormData();
    form.append('file', new Blob(['%PDF-1.4']), 'paper.pdf');

    await apiFetch('/x', { method: 'POST', body: form });

    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(init.headers['Content-Type']).toBeUndefined();
    expect(init.body).toBe(form);
  });
});
