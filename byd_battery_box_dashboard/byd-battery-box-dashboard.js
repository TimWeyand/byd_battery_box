class BYDBatteryBoxDashboard extends HTMLElement {
  static getConfigElement() {
    return document.createElement('byd-battery-box-dashboard-editor');
  }
  static getStubConfig() { return { entity: '', days: 3, title: 'BYD Battery Box' }; }
  setConfig(config) { this._config = config; }
  set hass(hass) { this._hass = hass; this.render(); }

  getCardSize() { return 6; }

  render() {
    if (!this._hass || !this._config) return;
    const root = this.shadowRoot || this.attachShadow({ mode: 'open' });
    root.innerHTML = '';
    const card = document.createElement('ha-card');
    card.header = this._config.title || 'BYD Battery Box';

    const style = document.createElement('style');
    style.textContent = `
      .wrap { padding: 12px; }
      .module { display: inline-block; margin: 0 12px; vertical-align: bottom; }
      .cell { width: 8px; margin: 0 1px; display: inline-block; position: relative; height: 220px; background: linear-gradient(to top, #f2f2f2 0%, #e5e5e5 100%);}
      .bar { position: absolute; bottom: 0; width: 100%; }
      .min { background: #d32f2f; }
      .cur { background: #4caf50; opacity: 0.75; }
      .max { background: #9e9e9e; opacity: .5; }
      .labels { text-align: center; font-size: 12px; margin-top: 4px; }
    `;

    const wrap = document.createElement('div');
    wrap.className = 'wrap';

    // Data source: sensors in this integration expose attributes with arrays for cell voltages over modules
    // We expect attribute 'cell_voltages' in entity state attributes: [{ m: 1, v: [mV,...] }, ...]
    const entId = this._config.entity || 'sensor.bms_1_cells_average_voltage';
    const st = this._hass.states[entId];
    if (!st) {
      wrap.innerHTML = `Entity not found: ${entId}`;
      card.appendChild(style); card.appendChild(wrap); root.appendChild(card); return;
    }

    const cellData = st.attributes.cell_voltages;
    const minKey = 'cell_voltages_min';
    const maxKey = 'cell_voltages_max';
    const minHist = st.attributes[minKey];
    const maxHist = st.attributes[maxKey];

    const minCfg = Number(this._config?.voltage_min ?? 3000);
    const maxCfg = Number(this._config?.voltage_max ?? 3700);
    const mvToScale = (mv, min=minCfg, max=maxCfg) => {
      const h = 200; // px
      const cl = Math.min(max, Math.max(min, mv));
      return Math.round((cl - min) / (max - min) * h);
    };

    if (Array.isArray(cellData)) {
      cellData.forEach((mod, idx) => {
        const moduleDiv = document.createElement('div');
        moduleDiv.className = 'module';

        const cells = mod.v || [];
        const minCells = (minHist && minHist[idx] && minHist[idx].v) ? minHist[idx].v : Array(cells.length).fill(cells[0]||0);
        const maxCells = (maxHist && maxHist[idx] && maxHist[idx].v) ? maxHist[idx].v : Array(cells.length).fill(cells[0]||0);

        cells.forEach((mv, i) => {
          const holder = document.createElement('div');
          holder.className = 'cell';

          const maxH = mvToScale(maxCells[i]);
          const curH = mvToScale(mv);
          const minH = mvToScale(minCells[i]);

          const maxBar = document.createElement('div'); maxBar.className = 'bar max'; maxBar.style.height = `${maxH}px`;
          const curBar = document.createElement('div'); curBar.className = 'bar cur'; curBar.style.height = `${curH}px`;
          const minBar = document.createElement('div'); minBar.className = 'bar min'; minBar.style.height = `${minH}px`;

          holder.appendChild(maxBar);
          holder.appendChild(curBar);
          holder.appendChild(minBar);
          moduleDiv.appendChild(holder);
        });

        const label = document.createElement('div');
        label.className = 'labels';
        label.textContent = `BMS${(st.attributes.tower||1)}.${mod.m}`;
        moduleDiv.appendChild(label);

        wrap.appendChild(moduleDiv);
      });
    } else {
      wrap.innerHTML = 'Entity has no attribute cell_voltages';
    }

    card.appendChild(style);
    card.appendChild(wrap);
    root.appendChild(card);
  }
}

customElements.define('byd-battery-box-dashboard', BYDBatteryBoxDashboard);

class BYDBatteryBoxDashboardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }
  set hass(hass) {
    this._hass = hass;
    this.render();
  }
  render() {
    if (!this._hass) return;
    const root = this.shadowRoot || this.attachShadow({ mode: 'open' });
    root.innerHTML = '';

    const style = document.createElement('style');
    style.textContent = `
      .row { display: flex; gap: 12px; margin: 8px 0; align-items: center; }
      .col { flex: 1; }
      .note { color: var(--secondary-text-color); font-size: 12px; }
    `;

    const wrap = document.createElement('div');

    // Entity picker filtered to this integration’s sensors by attributes
    const entityRow = document.createElement('div'); entityRow.className = 'row';
    const entityLabel = document.createElement('label'); entityLabel.textContent = 'Entity'; entityLabel.style.minWidth = '120px';
    const picker = document.createElement('ha-entity-picker');
    picker.hass = this._hass;
    picker.value = this._config.entity || '';
    picker.includeDomains = ['sensor'];
    picker.entityFilter = (e) => {
      const st = this._hass.states[e];
      if (!st) return false;
      // Prefer entities that expose the expected attribute structure
      const hasCells = Array.isArray(st.attributes?.cell_voltages);
      // Also narrow by id pattern used by this integration
      const looksLikeBYD = /^sensor\.bms_\d+_cells_average_voltage$/.test(e);
      return hasCells || looksLikeBYD;
    };
    picker.addEventListener('value-changed', (ev) => this._update({ entity: ev.detail?.value }));
    entityRow.append(entityLabel, picker);

    // Title
    const titleRow = document.createElement('div'); titleRow.className = 'row';
    const titleLabel = document.createElement('label'); titleLabel.textContent = 'Title'; titleLabel.style.minWidth = '120px';
    const title = document.createElement('paper-input');
    title.value = this._config.title || 'BYD Battery Box';
    title.addEventListener('value-changed', (ev) => this._update({ title: ev.detail?.value }));
    titleRow.append(titleLabel, title);

    // Days, voltage_min, voltage_max
    const cfgRow = document.createElement('div'); cfgRow.className = 'row';
    const days = document.createElement('paper-input'); days.className = 'col'; days.label = 'Days (history)'; days.type = 'number'; days.value = this._config.days ?? 3; days.min = 0; days.addEventListener('value-changed', (ev)=>this._update({ days: Number(ev.detail?.value) }));
    const vmin = document.createElement('paper-input'); vmin.className = 'col'; vmin.label = 'Voltage min (mV)'; vmin.type = 'number'; vmin.value = this._config.voltage_min ?? 3000; vmin.addEventListener('value-changed', (ev)=>this._update({ voltage_min: Number(ev.detail?.value) }));
    const vmax = document.createElement('paper-input'); vmax.className = 'col'; vmax.label = 'Voltage max (mV)'; vmax.type = 'number'; vmax.value = this._config.voltage_max ?? 3700; vmax.addEventListener('value-changed', (ev)=>this._update({ voltage_max: Number(ev.detail?.value) }));
    cfgRow.append(days, vmin, vmax);

    const note = document.createElement('div'); note.className = 'note'; note.textContent = 'Select a BYD sensor that exposes cell_voltages attributes (e.g., sensor.bms_1_cells_average_voltage).';

    wrap.append(entityRow, titleRow, cfgRow, note);
    root.append(style, wrap);
  }
  _update(patch) {
    this._config = { ...(this._config||{}), ...patch };
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config } }));
  }
}
customElements.define('byd-battery-box-dashboard-editor', BYDBatteryBoxDashboardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'byd-battery-box-dashboard',
  name: 'BYD Battery Box Dashboard',
  description: 'Visualize BYD cell voltages (min/cur/max) per module.',
});
