import { t } from "./i18n.js";
import { html, field, check, formError, button, body, panel, badge, fmt, label, results, timeline } from './ui.js';
export function providerForm(state, provider) {
  const editing = Boolean(provider);
  return html`<form id="provider-form" data-testid="provider-form">${formError()}
    ${editing ? html`<div class="actions provider-utilities">${button(t('provider.copyLink'), 'provider-share', provider.name)}</div>` : ''}<div class="form-row">
    ${field('name', t("copy.5df7bfb4b7"), provider?.name || '', { id: 'provider-name', required: true, disabled: editing, maxlength: 64, pattern: '[a-zA-Z0-9_-]+', hint: t("copy.f937a797fc") })}
    ${field('provider', t("copy.7899b9e18c"), provider?.provider || state.catalog[0]?.provider, { id: 'provider-type', required: true, choices: state.catalog.map(p => [p.provider, p.label || p.provider]) })}</div>
    ${field('api_base', t("copy.34218e4108"), provider?.api_base || '', { id: 'provider-base', type: 'url', maxlength: 2048 })}
    ${field('api_key', `API Key${provider?.has_api_key ? t("copy.6e95d2e34d") : ''}`, '', { id: 'provider-key', type: 'password', maxlength: 4096, placeholder: editing ? t("copy.2326dd3ab5") : t("copy.4042186ae3") })}
    <div id="searxng-options">${field('engines', t("copy.2179355f08"), (provider?.engines || []).join(', '), { id: 'provider-engines', hint: t("copy.0273bae09f") })}
      <div class="actions engine-utilities">${button(t("copy.fbfb7faeb3"), 'provider-common-engines')}</div>
      ${provider?.name ? html`<div class="note">${button(t("copy.d207f5cf9f"), 'provider-sync', provider.name)}<p>${t("copy.00097d89c4")}${(provider.verified_engines || []).join(', ') || t("copy.439e864e83")}</p>
        <p>${t("copy.8124cd7ac2")}${provider.engine_evidence || t("copy.d14675f943")}</p></div>` : ''}</div>
    ${field('timeout_ms', t("copy.7e43a2a1f9"), provider?.timeout_ms || 8000, { id: 'provider-timeout', type: 'number', required: true, min: 100, max: 60000, step: 100 })}
    <div id="openai-options" hidden>${field('search_model', t("copy.f92b786464"), provider?.search_model || 'gpt-4.1-mini', { id: 'provider-model', maxlength: 128 })}<div class="form-row">
      ${field('search_context_size', t("copy.24f986d2c8"), provider?.search_context_size || 'medium', { choices: [['low', t("copy.e3521db829")], ['medium', t("copy.fe4e7b3d04")], ['high', t("copy.61aacc9fd8")]] })}
      ${field('max_output_tokens', t("copy.c5fa526946"), provider?.max_output_tokens || 2048, { type: 'number', min: 128, max: 8192 })}</div><p class="section-foot">${t("copy.ceeb6fd77e")}</p></div>
    <div id="bensz-options" hidden>${field('estimated_cost_usd', t("copy.c028e16418"), provider?.estimated_cost_usd ?? 0.02,
      { id: 'provider-cost', type: 'number', min: 0, max: 10, step: '0.001', hint: t("copy.9c14dfd125") })}</div>
    ${field('source_family', t("copy.c77c8bc0db"), provider?.source_family || '', { maxlength: 64, hint: t("copy.88d77089f9") })}
    ${check('enabled', t("copy.4784ee7478"), provider?.enabled !== false)}
    <div class="form-actions sticky-actions">${button(t("common.cancel"), 'dialog-close')}<button class="btn" type="submit" value="test">${t("provider.saveTest")}</button><button class="btn primary" type="submit" value="save">${t("provider.save")}</button></div></form>`;
}
export function updateProviderFields(state, editing = false, change = false) {
  const form = document.getElementById('provider-form');
  if (!form) return;
  const type = form.elements.provider.value;
  const item = state.catalog.find(p => p.provider === type) || {};
  const federated = type === 'bensz_search';
  const base = form.elements.api_base;
  base.placeholder = item.default_api_base || 'https://your-search-service';
  base.required = ['searxng', 'bensz_search'].includes(type);
  document.getElementById('provider-base-hint').textContent = federated
    ? t("copy.e2763fa57e") : base.required ? t("copy.01d6979a15") : t("copy.d69547862e");
  document.getElementById('provider-key-hint').textContent = federated ? t("copy.b12412e2c8")
    : item.requires_api_key ? t("copy.03aadf4bf0") : t("copy.fe5989d68a");
  for (const [id, visible] of [['searxng-options', type === 'searxng'], ['openai-options', type === 'openai'], ['bensz-options', federated]]) {
    const group = document.getElementById(id);
    group.hidden = !visible;
    group.querySelectorAll('input,select').forEach(input => { input.disabled = !visible; });
  }
  form.elements.engines.placeholder = (item.default_engines || []).join(', ');
  form.elements.estimated_cost_usd.required = federated;
  form.elements.search_model.required = type === 'openai';
  if (!editing && change) form.elements.timeout_ms.value = type === 'openai' ? 30000 : federated ? 15000 : 8000;
}
export function providerPayload(form, original) {
  const fields = new FormData(form);
  const payload = { name: original?.name || fields.get('name'), provider: fields.get('provider'), api_key: fields.get('api_key') || '', api_base: fields.get('api_base') || '',
    engines: String(fields.get('engines') || '').split(',').map(s => s.trim()).filter(Boolean), timeout_ms: Number(fields.get('timeout_ms')), enabled: fields.has('enabled'), source_family: fields.get('source_family') || null };
  if (payload.provider === 'bensz_search') payload.estimated_cost_usd = Number(fields.get('estimated_cost_usd'));
  if (payload.provider === 'openai') Object.assign(payload, { search_model: fields.get('search_model'), search_context_size: fields.get('search_context_size'), max_output_tokens: Number(fields.get('max_output_tokens')) });
  return payload;
}
export function testForm(state, name) {
  const cache = state.tests[name];
  return html`<form id="test-form" data-provider="${name}" data-testid="provider-test"><p>${t("copy.90a3d113e9")}</p>
    ${field('query', t("copy.80996e730c"), cache?.query || 'Python official documentation', { id: 'test-query', maxlength: 1000, required: true })}${formError()}
    <div class="form-actions"><button class="btn primary" type="submit">${t("copy.ca02ccbd4e")}</button></div><div id="test-results" class="test-results" aria-live="polite">${cache ? testResults(cache.data) : ''}</div></form>`;
}
export function testResults(data) {
  return html`<div class="note ${data.ok ? '' : 'warning'}">${data.ok ? t("copy.4a19cb8a31") : t("copy.77c9e582e8")} · ${fmt(data.result_count)} ${t("copy.89ae1d3102")} ${fmt(data.latency_ms)} ms · ${label(data.category)}</div>
    ${results(data.results || [])}${data.debug ? timeline(data) : ''}`;
}
export function keyForm() {
  return html`<form id="key-form" data-testid="key-form">${formError()}
    ${field('name', t("copy.8b217f4aa1"), '', { id: 'key-name', required: true, maxlength: 100, placeholder: t("copy.c31f828824") })}
    ${field('expires_at', t("copy.baf7b96414"), '', { type: 'datetime-local', hint: t("copy.5cd4593544") })}
    <fieldset><legend>${t("copy.5abbb2d12c")}</legend>${check('scope_search', 'Search API · /search', true)}${check('scope_protocol', t("copy.64e805ad8b"), true)}</fieldset>
    <div class="form-actions sticky-actions">${button(t("common.cancel"), 'dialog-close')}<button class="btn primary" type="submit">${t("copy.ea10581c63")}</button></div></form>`;
}
export function userForm(user) {
  return html`<form id="user-form" data-testid="user-form">${formError()}
    ${field('username', t("account.username"), user?.username || '', { id: 'new-username', required: !user, disabled: Boolean(user), maxlength: 64, pattern: '[a-zA-Z0-9_.-]+' })}
    ${field('password', user ? t("copy.d5e1b4de41") : t("copy.df387080f9"), '', { id: 'new-password', type: 'password', required: !user, minlength: 12, maxlength: 256, autocomplete: 'new-password', hint: t("copy.b3d068be3f") })}
    ${field('role', t("copy.fd9063cba7"), user?.role || 'member', { id: 'new-role', choices: [['member', t("copy.6e6d6ddbb7")], ['admin', t("copy.e19796712f")]] })}
    ${user ? check('enabled', t("copy.10027ec295"), user.enabled !== false) : ''}
    <div class="form-actions sticky-actions">${button(t("common.cancel"), 'dialog-close')}<button class="btn primary" type="submit">${user ? t("copy.991bb7cfe5") : t("copy.37c825ff40")}</button></div></form>`;
}
export function importForm() {
  return html`<form id="import-form">${formError()}<div class="note">${t("copy.689fbf7f83")}</div>
    ${field('file', t("copy.ad11032fc1"), '', { type: 'file', required: true })}
    <div class="form-actions">${button(t("common.cancel"), 'dialog-close')}<button class="btn primary" type="submit">${t("copy.b48b651829")}</button></div></form>`;
}
export function reauthForm(state) {
  return html`<div class="dialog-head"><h2 id="reauth-title">${t("copy.1b18b001c2")}</h2></div><div class="dialog-body"><p>${t("copy.b124ea2341")}</p>
    <form id="reauth-form">${formError()}${field('username', t("account.username"), state.user.username, { id: 'reauth-username', required: true, disabled: true, autocomplete: 'username' })}
    ${field('password', t("account.password"), '', { id: 'reauth-password', type: 'password', required: true, autocomplete: 'current-password' })}<div class="form-actions"><button class="btn primary" type="submit">${t("copy.90528497a0")}</button></div></form></div>`;
}
