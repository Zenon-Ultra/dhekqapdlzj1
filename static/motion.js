(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  try { paused = localStorage.getItem('hyperx-motion-paused') === '1'; } catch (_) {}
  const control = document.createElement('button');
  control.className = 'hx-motion-control';
  control.type = 'button';
  const sync = () => {
    document.documentElement.classList.toggle('hx-motion-paused', paused || reduced.matches);
    control.textContent = paused || reduced.matches ? '모션 켜기' : '모션 멈추기';
    control.setAttribute('aria-pressed', String(!(paused || reduced.matches)));
    control.disabled = reduced.matches;
    control.title = reduced.matches ? '기기의 동작 줄이기 설정을 따르고 있습니다.' : '화면의 장식 애니메이션을 켜거나 멈춥니다.';
  };
  control.addEventListener('click', () => {
    paused = !paused;
    try { localStorage.setItem('hyperx-motion-paused', paused ? '1' : '0'); } catch (_) {}
    sync();
  });
  document.body.appendChild(control);
  reduced.addEventListener('change', sync);
  sync();

  // Existing API code remains responsible for the library. Observe only its DOM.
  const grid = document.getElementById('cardGrid');
  if (grid) {
    const counter = document.getElementById('hxBookCount');
    const update = () => {
      const cards = grid.querySelectorAll('.card');
      if (counter) counter.textContent = String(cards.length).padStart(2, '0');
      cards.forEach((card, index) => card.style.setProperty('--hx-order', Math.min(index, 8)));
    };
    new MutationObserver(update).observe(grid, {childList: true});
    update();
  }
  // Make the legacy sidebar controls keyboard accessible without replacing handlers.
  document.querySelectorAll('[data-hx-page="admin"] .nav-item').forEach(item => {
    item.setAttribute('role', 'button');
    item.tabIndex = 0;
    item.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); item.click(); }
    });
  });
})();
