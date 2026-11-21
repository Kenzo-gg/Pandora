(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const amount = text => Number(text.trim().replace(/[₱,]/g, ''));
  // from: the figures currently on screen, so a period change counts from them instead of from zero.
  function animateMetrics(from = []) {
    const counters = [];
    for (const [i, el] of [...document.querySelectorAll('.metric-number')].entries()) {
      const final = el.textContent.trim();
      const money = final.startsWith('₱');
      const value = amount(final);
      const begin = Number.isFinite(from[i]) ? from[i] : 0;
      if (reduced.matches || !Number.isFinite(value) || value === begin) continue;
      // The real figure must sit in .metric-final so it can be hidden while the counter runs.
      if (!el.querySelector('.metric-final')) {
        const finalSpan = document.createElement('span');
        finalSpan.className = 'metric-final';
        finalSpan.append(...el.childNodes);
        el.append(finalSpan);
      }
      const frame = document.createElement('span');
      frame.className = 'metric-frame';
      frame.setAttribute('aria-hidden', 'true');
      el.append(frame);
      el.classList.add('metric-running');
      const formatter = new Intl.NumberFormat('en-PH', {
        minimumFractionDigits: money ? 2 : 0, maximumFractionDigits: money ? 2 : 0
      });
      counters.push({el,frame,value,begin,formatter,money});
    }
    const start = performance.now();
    function count(now) {
      const t = reduced.matches ? 1 : Math.min(1,(now-start)/1100);
      for (const {el,frame,value,begin,formatter,money} of counters) {
        if (t === 1) {frame.remove();el.classList.remove('metric-running');}
        else frame.textContent = (money ? '₱' : '') + formatter.format(begin + (value-begin)*(1-(1-t)**3));
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
        // Read the on-screen value (mid-count if a count is still running) so the next count continues from it.
        const from = [...center.querySelectorAll('.metric-number')]
          .map(el => amount((el.querySelector('.metric-frame') || el).textContent));
        const swap = () => {
          center.replaceChildren(...Array.from(updated.childNodes));
          center.classList.add('swapped');
          animateMetrics(from);
        };
        // The old panel dissolves into the new one; without view transitions it swaps instantly.
        if (document.startViewTransition && !reduced.matches) document.startViewTransition(swap);
        else swap();
        history.replaceState(null,'',url);
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
  const DISMISS_MS = 8000; // matches the 8s drain bar in motion.css
  for (const toast of stack.children) {
    let timer;
    function pause() {
      clearTimeout(timer);
      toast.classList.remove('timing');
    }
    function dismiss() {
      if (toast.classList.contains('leaving')) return;
      pause();
      // Take the toast out of the layout at once (pinned where it is) so the others slide into its gap while it fades.
      const others = [...stack.children].filter(t => t !== toast && !t.classList.contains('leaving'));
      const before = others.map(t => t.getBoundingClientRect().top);
      const bottom = stack.clientHeight - toast.offsetTop - toast.offsetHeight;
      Object.assign(toast.style, {position:'absolute', left:'0', right:'0', bottom:bottom + 'px'});
      toast.classList.add('leaving');
      if (!reduced.matches) others.forEach((t, i) => {
        const dy = before[i] - t.getBoundingClientRect().top;
        if (dy) t.animate([{transform:`translateY(${dy}px)`}, {transform:'none'}], {duration:280, easing:'cubic-bezier(.22,1,.36,1)'});
      });
      setTimeout(() => toast.remove(), reduced.matches ? 0 : 170);
    }
    function schedule() {
      pause();
      // Warnings (such as reorder alerts) stay until the user dismisses them.
      if (toast.matches(':hover, :focus-within, .warning')) return;
      void toast.offsetWidth; // restart the drain bar from full
      toast.classList.add('timing');
      timer = setTimeout(dismiss, DISMISS_MS);
    }
    toast.querySelector('button').addEventListener('click',dismiss);
    toast.onpointerenter = toast.onfocusin = pause;
    toast.onpointerleave = schedule;
    toast.onfocusout = () => setTimeout(schedule,0);
    schedule();
  }
  // Saves (POST forms) show a spinner on the clicked button and ignore repeat clicks until the page answers.
  // GET forms are left alone: PDF downloads never leave the page, so a spinner there would never stop.
  document.addEventListener('submit', event => {
    const form = event.target;
    if (event.defaultPrevented || form.method !== 'post') return; // e.g. a cancelled confirm()
    if (form.dataset.busy) { event.preventDefault(); return; }
    form.dataset.busy = 'true';
    event.submitter?.setAttribute('aria-busy', 'true');
  });
  // Coming back with the Back button restores the page from cache, so clear any leftover busy state.
  addEventListener('pageshow', () => {
    for (const form of document.querySelectorAll('form[data-busy]')) delete form.dataset.busy;
    for (const button of document.querySelectorAll('button[aria-busy=true]')) button.removeAttribute('aria-busy');
  });
})();
