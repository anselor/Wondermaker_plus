(function () {
  'use strict';
  const plan = window.WMP_UI_PLAN;
  const byId = id => document.getElementById(id);
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let selected = 'S01';
  const labels = {standalone: 'Standalone WM+', openace: 'openACE present', unavailable: 'Backend unavailable'};
  function tab(id) {
    const button = document.querySelector('[data-tab="' + id + '"]');
    if (!button) return;
    document.querySelectorAll('[role="tabpanel"]').forEach(panel => {panel.hidden = panel.id !== id;});
    document.querySelectorAll('[data-tab]').forEach(item => item.setAttribute('aria-selected', String(item.dataset.tab === id)));
  }
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {tab(button.dataset.tab); history.replaceState(null, '', '#' + button.dataset.tab);}));
  function detail() {
    const screen = plan.screens.find(item => item.id === selected);
    const mode = byId('mode').value;
    if (!screen) {byId('detail').textContent = 'Choose a screen.'; return;}
    byId('detail').innerHTML = '<span class="badge">' + escape(screen.id) + ' · ' + escape(screen.decision) + '</span><span class="badge">' + escape(screen.phase) + '</span>' +
      '<h2>' + escape(screen.name) + '</h2>' +
      '<section><h3>Stock WM GUI</h3><p>' + escape(screen.stock) + '</p></section>' +
      '<section><h3>Current WM+ state</h3><p>' + escape(screen.current) + '</p></section>' +
      '<section><h3>Proposed target</h3><p>' + escape(screen.target) + '</p></section>' +
      '<section><h3>' + escape(labels[mode]) + '</h3><p>' + escape(screen[mode]) + '</p></section>' +
      '<div class="wireframe"><div class="demo"><strong>PROPOSED STRUCTURE · NOT A LIVE SCREEN</strong><span>' + escape(labels[mode]) + '</span></div>' +
      '<div class="screen-name">' + escape(screen.name) + '</div>' +
      '<div class="head-row">' + (mode === 'openace' ? 'Example identity: Tool T4 · Head 4 (h3) · hand-fed' : mode === 'standalone' ? 'Example selection: physical Head 4 · declared filament' : 'Displayed state is stale. No new material or recovery motion.') + '</div>' +
      (screen.id === 'S06' ? '<div class="toolbar"><label>Distance step (illustrative) <select' + (mode === 'unavailable' ? ' disabled' : '') + '><option>1 mm</option><option>5 mm</option><option>10 mm</option><option>25 mm</option><option>50 mm</option></select></label><label>Target °C (example) <input type="number" value="220" style="width:90px"' + (mode === 'unavailable' ? ' disabled' : '') + '></label></div>' : '') +
      (screen.id === 'S07' ? '<div class="toolbar"><label>Brand <select disabled><option>Catalogue API TBD</option></select></label><label>Material <select disabled><option>Catalogue API TBD</option></select></label><label>Colour (example) <input type="color" value="#22c3e6"' + (mode === 'unavailable' ? ' disabled' : '') + '></label><label>Pressure advance <select disabled><option>PA contract TBD</option></select></label></div>' : '') +
      '<div class="action-row">' + screen.controls.map(name => '<button type="button" data-preview-action="' + escape(name) + '"' + (mode === 'unavailable' ? ' disabled' : '') + '>' + escape(name) + '</button>').join('') + '</div>' +
      '<div class="footer"><span class="muted">Illustrative navigation and control grouping</span><button type="button" class="stop" data-preview-action="Cancel / Stop print">Cancel / Stop print</button></div>' +
      '<div class="prototype-result" id="prototype-result">Preview only. These labels do not establish implemented actions or current permissions.</div></div>';
    byId('detail').querySelectorAll('[data-preview-action]').forEach(button => button.addEventListener('click', () => {
      byId('prototype-result').textContent = 'Design preview: “' + button.dataset.previewAction + '”. A real operation would require current owner admission and an explicit action. Nothing was sent.';
    }));
  }
  function screens() {
    const query = byId('query').value.toLowerCase();
    const decision = byId('decision').value;
    const shown = plan.screens.filter(screen => (decision === 'all' || screen.decision === decision) && JSON.stringify(screen).toLowerCase().includes(query));
    if (!shown.some(screen => screen.id === selected)) selected = shown.length ? shown[0].id : null;
    byId('screen-list').innerHTML = shown.length ? shown.map(screen => '<button type="button" data-screen="' + escape(screen.id) + '" aria-current="' + String(screen.id === selected) + '"><span class="badge">' + escape(screen.decision) + '</span>' + escape(screen.id + ' · ' + screen.name) + '</button>').join('') : '<p>No matching screens.</p>';
    byId('screen-list').querySelectorAll('[data-screen]').forEach(button => button.addEventListener('click', () => {selected = button.dataset.screen; screens();}));
    detail();
  }
  byId('mode').addEventListener('change', detail);
  byId('decision').addEventListener('change', screens);
  byId('query').addEventListener('input', screens);
  byId('requirement-grid').innerHTML = plan.requirements.map(requirement => '<article class="card"><span class="badge">' + escape(requirement.scope) + ' · ' + escape(requirement.phase) + '</span><h3>' + escape(requirement.id + ' · ' + requirement.name) + '</h3><p>' + escape(requirement.behavior) + '</p><p class="muted">Backend / API: ' + escape(requirement.backend) + '</p></article>').join('');
  byId('feature-grid').innerHTML = plan.features.map(feature => '<article class="card"><span class="badge">' + escape(feature.status) + '</span><h3>' + escape(feature.id + ' · ' + feature.name) + '</h3><p>' + escape(feature.current) + '</p><p class="muted">Target: ' + escape(feature.target) + '</p></article>').join('');
  byId('new-views').innerHTML = plan.new_screens.map(view => '<article class="card new-view"><h3>' + escape(view.id + ' · ' + view.name) + '</h3><p>' + escape(view.content) + '</p><p class="muted">Boundary: ' + escape(view.boundary) + '</p></article>').join('');
  byId('flow-select').innerHTML = plan.flows.map(flow => '<option value="' + escape(flow.id) + '">' + escape(flow.title) + '</option>').join('');
  function flow() {
    const current = plan.flows.find(item => item.id === byId('flow-select').value);
    byId('flow-content').innerHTML = '<div class="flow">' + current.steps.map((step, index) => '<div class="step"><b>STEP ' + (index + 1) + '</b>' + escape(step) + '</div>').join('') + '</div><p class="muted">' + escape(current.note) + '</p>';
  }
  byId('flow-select').addEventListener('change', flow);
  byId('gallery').innerHTML = plan.history.map(image => '<figure><a href="' + escape(image.file) + '"><img src="' + escape(image.file) + '" alt="' + escape(image.title) + '" loading="lazy"></a><figcaption>' + escape(image.title) + '</figcaption></figure>').join('');
  byId('phase-list').innerHTML = plan.phases.map(phase => '<article class="phase"><b>' + escape(phase.id) + '</b><div><h3>' + escape(phase.name) + '</h3><p class="muted">Exit gate: ' + escape(phase.exit) + '</p></div></article>').join('');
  screens(); flow(); tab(location.hash.slice(1) || 'screens');
  window.addEventListener('hashchange', () => tab(location.hash.slice(1)));
})();
