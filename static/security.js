(() => {
  const token = document.querySelector('meta[name="csrf-token"]').content;
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin === location.origin) {
      const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-CSRF-Token', token);
      options = { ...options, headers };
    }
    return originalFetch(input, options);
  };
  const OriginalEventSource = window.EventSource;
  window.EventSource = class extends OriginalEventSource {
    constructor(input, options) {
      const url = new URL(input, location.href);
      if (url.origin === location.origin) url.searchParams.set('_csrf', token);
      super(url.href, options);
    }
  };
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href="/logout"]');
    if (link) link.href = '/logout?_csrf=' + encodeURIComponent(token);
  });
})();
