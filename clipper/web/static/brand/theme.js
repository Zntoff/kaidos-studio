/* Run before styles to restore appearance without a flash. No account or media state changes. */
(() => {
  const key = 'kairos.theme', choices = ['dark', 'light', 'system'];
  const system = matchMedia('(prefers-color-scheme: light)');
  let preference = 'dark';
  try { const saved = localStorage.getItem(key); if (choices.includes(saved)) preference = saved; } catch {}
  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'light' : 'dark') : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#FFFFFF' : '#000000');
  }
  window.KairosTheme = {
    get preference() { return preference; },
    set(value) { if (!choices.includes(value)) return; preference = value; try { localStorage.setItem(key, value); } catch {} apply(); },
  };
  system.addEventListener('change', apply);
  window.addEventListener('storage', e => { if (e.key === key) { preference = choices.includes(e.newValue) ? e.newValue : 'dark'; apply(); } });
  apply();
})();
