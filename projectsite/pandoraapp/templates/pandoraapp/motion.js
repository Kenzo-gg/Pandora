(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function animateMetrics() {
    const counters = [];
    for (const el of document.querySelectorAll('.metric-number')) {
      const final = el.textContent.trim();
      const money = final.startsWith('₱');
      const value = Number(final.replace(/[₱,]/g, ''));
      if (reduced.matches || !Number.isFinite(value) || !value) continue;
      const frame = document.createElement('span');
      frame.className = 'metric-frame';
      frame.setAttribute('aria-hidden', 'true');
      el.append(frame);
      el.classList.add('metric-running');
      const formatter = new Intl.NumberFormat('en-PH', {
        minimumFractionDigits: money ? 2 : 0, maximumFractionDigits: money ? 2 : 0
      });
      counters.push({el,frame,value,formatter,money});
    }
    const start = performance.now();
    function count(now) {
      const t = reduced.matches ? 1 : Math.min(1,(now-start)/760);
      for (const {el,frame,value,formatter,money} of counters) {
        if (t === 1) {frame.remove();el.classList.remove('metric-running');}
        else frame.textContent = (money ? '₱' : '') + formatter.format(value*(1-(1-t)**3));
      }
      if (t < 1) requestAnimationFrame(count);
    }
    if (counters.length) requestAnimationFrame(count);
  }
  animateMetrics();
  const filter = document.querySelector('#sales-filter');
  if (filter && window.fetch && window.AbortController) {
    let pending;
    const select = filter.elements.period;
    filter.classList.add('enhanced');
    select.addEventListener('change', () => filter.requestSubmit());
    filter.addEventListener('submit', async event => {
      event.preventDefault();
      pending?.abort();
      const controller = new AbortController();
      pending = controller;
      const url = new URL(location.href);
      url.searchParams.set('period', select.value);
      const center = document.querySelector('.center-col');
      center.setAttribute('aria-busy','true');
      try {
        const response = await fetch(url, {signal:controller.signal});
        if (!response.ok || response.redirected) throw Error();
        const doc = new DOMParser().parseFromString(await response.text(),'text/html');
        const updated = doc.querySelector('.center-col');
        if (!updated) throw Error();
        if (controller.signal.aborted) return;
        center.replaceChildren(...Array.from(updated.childNodes));
        history.replaceState(null,'',url);
        animateMetrics();
      } catch (error) {
        if (!controller.signal.aborted) location.assign(url);
      } finally {
        if (pending === controller) center.removeAttribute('aria-busy');
      }
    });
  }
  const stack = document.querySelector('.toasts');
  if (document.querySelector('form .errorlist')) {
    const toast = document.createElement('div');
    toast.className = 'toast error';
    toast.textContent = 'Please review the highlighted form errors.';
    const close = document.createElement('button');
    close.type = 'button';close.textContent = '×';
    close.setAttribute('aria-label','Dismiss notification');
    toast.append(close);stack.append(toast);
  }
  for (const toast of stack.children) {
    let timer;
    function dismiss() {
      clearTimeout(timer);
      toast.classList.add('leaving');
      setTimeout(() => toast.remove(), reduced.matches ? 0 : 170);
    }
    function schedule() {
      clearTimeout(timer);
      if (!toast.matches(':hover, :focus-within')) timer = setTimeout(dismiss,8000);
    }
    toast.querySelector('button').addEventListener('click',dismiss);
    toast.onpointerenter = toast.onfocusin = () => clearTimeout(timer);
    toast.onpointerleave = schedule;
    toast.onfocusout = () => setTimeout(schedule,0);
    schedule();
  }
})();
