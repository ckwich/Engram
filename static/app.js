(() => {
  'use strict';

  let currentView = 'grid';
  let activeTag = '';
  let currentViewKey = null;
  let searchTimeout = null;
  let editMode = false;
  let staleTabActive = false;
  let usageTabActive = false;
  let evalTabActive = false;

  const pageConfig = document.body.dataset;
  const writeAuthRequired = pageConfig.writeAuthRequired === 'true';
  const writeTokenConfigured = pageConfig.writeTokenConfigured === 'true';
  const writeTokenHeader = pageConfig.writeTokenHeader || 'X-Engram-Write-Token';

  function init() {
    initActionHandlers();
    initMemoryCards();
    initViewToggle();
    initTagFiltering();
    initSelectHandlers();
    initSearch();
    initModalCloseHandlers();
  }

  function initActionHandlers() {
    document.addEventListener('click', event => {
      const control = event.target.closest('[data-action]');
      if (!control) return;

      const action = control.dataset.action;
      event.preventDefault();

      if (action === 'open-create') openCreateModal();
      else if (action === 'save-write-token') saveWriteToken();
      else if (action === 'toggle-stale') toggleStaleTab();
      else if (action === 'toggle-usage') toggleUsageTab();
      else if (action === 'toggle-eval') toggleEvalTab();
      else if (action === 'run-eval') loadEvalTab();
      else if (action === 'apply-template') applyTemplate(control.dataset.template);
      else if (action === 'close-modal') closeModal(control.dataset.modalId);
      else if (action === 'save-memory') saveMemory();
      else if (action === 'delete-current') deleteCurrentMemory();
      else if (action === 'edit-current') editCurrentMemory();
      else if (action === 'mark-reviewed') {
        markReviewed(control.dataset.key, control.dataset.staleType, control);
      } else if (action === 'load-full') {
        loadFullMemory(control.dataset.key, control);
      } else if (action === 'view-edit' || action === 'open-related') {
        openViewModal(control.dataset.key);
      }
    });
  }

  function initMemoryCards() {
    const container = document.getElementById('memory-container');
    container.addEventListener('click', event => {
      const card = event.target.closest('.memory-card');
      if (card && card.dataset.key) openViewModal(card.dataset.key);
    });
  }

  function initViewToggle() {
    document.querySelectorAll('.view-toggle .btn').forEach(button => {
      button.addEventListener('click', () => {
        document.querySelectorAll('.view-toggle .btn').forEach(item => item.classList.remove('active'));
        button.classList.add('active');
        currentView = button.dataset.view;
        const container = document.getElementById('memory-container');
        container.className = currentView === 'grid' ? 'memory-grid' : 'memory-list';
      });
    });
  }

  function initTagFiltering() {
    const tagList = document.getElementById('tag-list');
    const tagSearchInput = document.getElementById('tag-search-input');

    tagList.addEventListener('click', event => {
      const item = event.target.closest('li');
      if (!item) return;
      document.querySelectorAll('#tag-list li').forEach(tag => tag.classList.remove('active'));
      item.classList.add('active');
      activeTag = item.dataset.tag;
      filterByTag();
    });

    tagSearchInput.addEventListener('input', () => {
      const query = tagSearchInput.value.trim().toLowerCase();
      document.querySelectorAll('#tag-list li').forEach(item => {
        if (!item.dataset.tag) {
          item.classList.remove('hidden');
          return;
        }
        item.classList.toggle('hidden', !item.dataset.tag.toLowerCase().includes(query));
      });
    });
  }

  function initSelectHandlers() {
    document.getElementById('stale-type-filter').addEventListener('change', loadStaleTab);
    document.getElementById('usage-days-filter').addEventListener('change', loadUsageTab);
  }

  function initSearch() {
    const searchInput = document.getElementById('search-input');
    const searchResults = document.getElementById('search-results');
    const memoryContainer = document.getElementById('memory-container');

    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimeout);
      const query = searchInput.value.trim();
      if (!query) {
        searchResults.classList.add('hidden');
        if (!staleTabActive && !usageTabActive && !evalTabActive) memoryContainer.classList.remove('hidden');
        return;
      }
      staleTabActive = false;
      usageTabActive = false;
      evalTabActive = false;
      document.getElementById('btn-stale-tab').classList.remove('active');
      document.getElementById('btn-usage-tab').classList.remove('active');
      document.getElementById('btn-eval-tab').classList.remove('active');
      document.getElementById('stale-panel').classList.add('hidden');
      document.getElementById('usage-panel').classList.add('hidden');
      document.getElementById('eval-panel').classList.add('hidden');
      searchTimeout = setTimeout(() => doSearch(query), 300);
    });

    searchResults.addEventListener('click', event => {
      if (event.target.closest('[data-action]')) return;
      const result = event.target.closest('.search-result');
      if (result) expandResult(result);
    });
  }

  function initModalCloseHandlers() {
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', event => {
        if (event.target === overlay) overlay.classList.remove('active');
      });
    });

    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(modal => {
          modal.classList.remove('active');
        });
      }
    });
  }

  function getWriteToken() {
    return sessionStorage.getItem('engramWriteToken') || '';
  }

  function getWriteHeaders(baseHeaders = {}) {
    const headers = { ...baseHeaders };
    if (writeAuthRequired) {
      const token = getWriteToken();
      if (token) headers[writeTokenHeader] = token;
    }
    return headers;
  }

  function saveWriteToken() {
    const input = document.getElementById('write-token-input');
    const status = document.getElementById('write-token-status');
    if (!input || !status) return;
    const token = input.value.trim();
    if (!token) {
      status.textContent = 'Token required.';
      return;
    }
    sessionStorage.setItem('engramWriteToken', token);
    input.value = '';
    status.textContent = 'Writes unlocked for this tab.';
  }

  function explainWriteAuthFailure(response) {
    if (response.status === 401) return 'Invalid write token. Re-enter the token and try again.';
    if (response.status === 403 && !writeTokenConfigured) {
      return 'Server is exposed without ENGRAM_WEBUI_WRITE_TOKEN configured, so writes are disabled.';
    }
    if (response.status === 403) return 'Write token required. Enter the token and try again.';
    return `HTTP ${response.status}`;
  }

  function filterByTag() {
    document.querySelectorAll('.memory-card').forEach(card => {
      if (!activeTag) {
        card.classList.remove('hidden');
        return;
      }
      const tags = (card.dataset.tags || '').split(',');
      card.classList.toggle('hidden', !tags.includes(activeTag));
    });
  }

  function toggleStaleTab() {
    staleTabActive = !staleTabActive;
    usageTabActive = false;
    evalTabActive = false;
    const button = document.getElementById('btn-stale-tab');
    const usageButton = document.getElementById('btn-usage-tab');
    const evalButton = document.getElementById('btn-eval-tab');
    const stalePanel = document.getElementById('stale-panel');
    const usagePanel = document.getElementById('usage-panel');
    const evalPanel = document.getElementById('eval-panel');
    const memoryContainer = document.getElementById('memory-container');
    const searchResults = document.getElementById('search-results');

    usageButton.classList.remove('active');
    evalButton.classList.remove('active');
    usagePanel.classList.add('hidden');
    evalPanel.classList.add('hidden');

    if (staleTabActive) {
      button.classList.add('active');
      stalePanel.classList.remove('hidden');
      stalePanel.classList.add('active');
      memoryContainer.classList.add('hidden');
      searchResults.classList.add('hidden');
      loadStaleTab();
    } else {
      button.classList.remove('active');
      stalePanel.classList.add('hidden');
      stalePanel.classList.remove('active');
      memoryContainer.classList.remove('hidden');
    }
  }

  function toggleUsageTab() {
    usageTabActive = !usageTabActive;
    staleTabActive = false;
    evalTabActive = false;
    const usageButton = document.getElementById('btn-usage-tab');
    const staleButton = document.getElementById('btn-stale-tab');
    const evalButton = document.getElementById('btn-eval-tab');
    const usagePanel = document.getElementById('usage-panel');
    const stalePanel = document.getElementById('stale-panel');
    const evalPanel = document.getElementById('eval-panel');
    const memoryContainer = document.getElementById('memory-container');
    const searchResults = document.getElementById('search-results');

    staleButton.classList.remove('active');
    evalButton.classList.remove('active');
    stalePanel.classList.add('hidden');
    stalePanel.classList.remove('active');
    evalPanel.classList.add('hidden');
    usageButton.classList.toggle('active', usageTabActive);
    usagePanel.classList.toggle('hidden', !usageTabActive);
    memoryContainer.classList.toggle('hidden', usageTabActive);
    searchResults.classList.add('hidden');
    if (usageTabActive) loadUsageTab();
  }

  function toggleEvalTab() {
    evalTabActive = !evalTabActive;
    staleTabActive = false;
    usageTabActive = false;
    const evalButton = document.getElementById('btn-eval-tab');
    const staleButton = document.getElementById('btn-stale-tab');
    const usageButton = document.getElementById('btn-usage-tab');
    const evalPanel = document.getElementById('eval-panel');
    const stalePanel = document.getElementById('stale-panel');
    const usagePanel = document.getElementById('usage-panel');
    const memoryContainer = document.getElementById('memory-container');
    const searchResults = document.getElementById('search-results');

    staleButton.classList.remove('active');
    usageButton.classList.remove('active');
    stalePanel.classList.add('hidden');
    stalePanel.classList.remove('active');
    usagePanel.classList.add('hidden');
    evalButton.classList.toggle('active', evalTabActive);
    evalPanel.classList.toggle('hidden', !evalTabActive);
    memoryContainer.classList.toggle('hidden', evalTabActive);
    searchResults.classList.add('hidden');
    if (evalTabActive) loadEvalTab();
  }

  async function loadEvalTab() {
    document.getElementById('eval-summary-cards').innerHTML =
      '<div class="loading-row">Running retrieval eval...</div>';
    document.getElementById('eval-scenario-list').innerHTML = '';
    try {
      const response = await fetch('/api/eval/retrieval');
      if (!response.ok) throw new Error('Retrieval eval API unavailable');
      const report = await response.json();
      renderEvalReport(report);
    } catch (error) {
      document.getElementById('eval-summary-cards').innerHTML =
        `<div class="loading-row">Error running eval: ${esc(error.message)}</div>`;
    }
  }

  function renderEvalReport(report) {
    const summary = report.summary || {};
    const passed = safeInteger(summary.passed);
    const failed = safeInteger(summary.failed);
    const scenarioCount = safeInteger(summary.scenario_count);
    const status = summary.status || (failed ? 'fail' : 'pass');
    document.getElementById('eval-summary-cards').innerHTML = `
      <div class="usage-card"><span>${esc(status)}</span><label>status</label></div>
      <div class="usage-card"><span>${scenarioCount}</span><label>scenarios</label></div>
      <div class="usage-card"><span>${passed}</span><label>passed</label></div>
      <div class="usage-card"><span>${failed}</span><label>failed</label></div>
    `;
    document.getElementById('eval-scenario-list').innerHTML = (report.scenarios || []).map(scenario => `
      <div class="usage-call-row eval-scenario-row">
        <strong>${esc(scenario.id)}</strong>
        <span>${esc(scenario.status)}</span>
        <span>${safeInteger((scenario.search || {}).count)} candidates</span>
        <span>${safeInteger(((scenario.context_pack || {}).selected_chunk_count))} chunks</span>
      </div>
    `).join('') || '<div class="loading-row">No scenarios returned.</div>';
  }

  async function loadUsageTab() {
    const days = document.getElementById('usage-days-filter').value;
    document.getElementById('usage-summary-cards').innerHTML =
      '<div class="loading-row">Loading usage summary...</div>';
    document.getElementById('usage-tool-bars').innerHTML = '';
    document.getElementById('usage-warnings').innerHTML = '';
    document.getElementById('usage-call-list').innerHTML = '';
    try {
      const [summaryResponse, callsResponse] = await Promise.all([
        fetch(`/api/usage/summary?days=${encodeURIComponent(days)}`),
        fetch('/api/usage/calls?limit=50'),
      ]);
      if (!summaryResponse.ok || !callsResponse.ok) throw new Error('Usage API unavailable');
      const summary = await summaryResponse.json();
      const calls = await callsResponse.json();
      renderUsageSummary(summary);
      renderUsageCalls(calls.calls || []);
    } catch (error) {
      document.getElementById('usage-summary-cards').innerHTML =
        `<div class="loading-row">Error loading usage: ${esc(error.message)}</div>`;
    }
  }

  function renderUsageSummary(summary) {
    const totalCalls = safeInteger(summary.total_calls);
    const totalInputTokens = safeInteger(summary.total_input_tokens);
    const totalResponseTokens = safeInteger(summary.total_response_tokens);
    const averageResponseTokens = safeInteger(summary.avg_response_tokens);

    document.getElementById('usage-summary-cards').innerHTML = `
      <div class="usage-card"><span>${totalCalls}</span><label>calls</label></div>
      <div class="usage-card"><span>${totalInputTokens}</span><label>input est.</label></div>
      <div class="usage-card"><span>${totalResponseTokens}</span><label>response est.</label></div>
      <div class="usage-card"><span>${averageResponseTokens}</span><label>avg response</label></div>
    `;
    const tools = Object.entries(summary.by_tool || {});
    const maxTokens = tools.reduce((max, [, data]) => Math.max(max, safeInteger(data.response_tokens)), 1);
    document.getElementById('usage-tool-bars').innerHTML = tools.map(([tool, data]) => {
      const responseTokens = safeInteger(data.response_tokens);
      const callCount = safeInteger(data.call_count);
      const percent = Math.round((responseTokens / maxTokens) * 100);
      return `
        <div class="usage-bar-row">
          <span>${esc(tool)} <small>${callCount} calls</small></span>
          <div class="usage-bar"><i class="${usageWidthClass(percent)}"></i></div>
          <strong>${responseTokens}</strong>
        </div>
      `;
    }).join('') || '<div class="loading-row">No usage recorded yet.</div>';
    document.getElementById('usage-warnings').innerHTML = (summary.warnings || []).map(warning => `
      <span class="usage-warning">${esc(warning.tool || 'tool')}: ${esc(warning.kind || 'warning')}</span>
    `).join('');
  }

  function renderUsageCalls(calls) {
    document.getElementById('usage-call-list').innerHTML = calls.map(call => `
      <div class="usage-call-row">
        <strong>${esc(call.tool)}</strong>
        <span>${esc(call.status)}</span>
        <span>${safeInteger(call.response_token_estimate)} response tokens</span>
        <span>${safeInteger(call.duration_ms)} ms</span>
      </div>
    `).join('') || '<div class="loading-row">No recent calls.</div>';
  }

  function usageWidthClass(percent) {
    const safePercent = Number.isFinite(percent) ? percent : 0;
    const bucket = Math.max(0, Math.min(100, Math.round(safePercent / 5) * 5));
    return `usage-width-${bucket}`;
  }

  function safeInteger(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.round(number) : 0;
  }

  async function loadStaleTab() {
    const listEl = document.getElementById('stale-list');
    const filterType = document.getElementById('stale-type-filter').value;
    listEl.innerHTML = '<div class="loading-row">Loading stale memories...</div>';

    try {
      const response = await fetch(`/api/stale?type=${encodeURIComponent(filterType)}`);
      const items = await response.json();

      if (!items.length) {
        listEl.innerHTML = '<div class="empty-state"><div class="icon">&#x2705;</div><p>No stale memories found.</p></div>';
        return;
      }

      listEl.innerHTML = items.map(memory => {
        const badge = {
          time: '<span class="stale-badge stale-time">Time stale</span>',
          code: '<span class="stale-badge stale-code">Code changed</span>',
          both: '<span class="stale-badge stale-both">Time + Code</span>',
        }[memory.stale_type] || '';
        const tags = (memory.tags || []).map(tag => `<span class="tag-chip">${esc(tag)}</span>`).join('');
        return `
          <div class="stale-row" data-key="${esc(memory.key)}" data-stale-type="${esc(memory.stale_type)}">
            <div class="stale-row-header">
              ${badge}
              <span class="stale-title">${esc(memory.title)}</span>
              <button
                class="btn btn-sm stale-reviewed-btn"
                type="button"
                data-action="mark-reviewed"
                data-key="${esc(memory.key)}"
                data-stale-type="${esc(memory.stale_type)}"
              >Mark Reviewed</button>
            </div>
            <div class="stale-row-meta">
              <span class="stale-key">${esc(memory.key)}</span>
              <span class="stale-detail">${esc(memory.stale_detail)}</span>
            </div>
            <div class="tags">${tags}</div>
          </div>
        `;
      }).join('');
    } catch (error) {
      listEl.innerHTML = `<div class="loading-row">Error loading stale memories: ${esc(error.message)}</div>`;
    }
  }

  async function markReviewed(key, staleType, button) {
    button.disabled = true;
    button.textContent = 'Saving...';
    try {
      const response = await fetch(`/api/memory/${encodeURIComponent(key)}/reviewed`, {
        method: 'POST',
        headers: getWriteHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ stale_type: staleType }),
      });
      if (!response.ok) throw new Error(explainWriteAuthFailure(response));
      const row = button.closest('.stale-row');
      row.classList.add('is-fading');
      setTimeout(() => row.remove(), 300);
    } catch (error) {
      button.textContent = 'Error';
      button.disabled = false;
    }
  }

  async function doSearch(query) {
    const memoryContainer = document.getElementById('memory-container');
    const searchResults = document.getElementById('search-results');
    memoryContainer.classList.add('hidden');
    searchResults.classList.remove('hidden');
    searchResults.innerHTML = '<div class="loading-row">Searching...</div>';

    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=10`);
      const results = await response.json();
      if (!results.length) {
        searchResults.innerHTML = '<div class="empty-state"><p>No results found.</p></div>';
        return;
      }
      searchResults.innerHTML = results.map(result => {
        const score = Number(result.score);
        const scoreLabel = Number.isFinite(score) ? `${(score * 100).toFixed(0)}%` : '0%';
        return `
          <div class="search-result" data-key="${esc(result.key)}" data-chunk-id="${esc(result.chunk_id)}">
            <div class="result-header">
              <span class="score">${scoreLabel}</span>
              <span class="result-title">${esc(result.title)}</span>
            </div>
            <div class="result-meta">key: ${esc(result.key)} &middot; chunk: ${esc(result.chunk_id)}</div>
            <div class="snippet">${esc(result.snippet)}</div>
            <div class="tags mt-1">${(result.tags || []).map(tag => `<span class="tag-chip">${esc(tag)}</span>`).join('')}</div>
            <div class="expanded-container"></div>
          </div>
        `;
      }).join('');
    } catch (error) {
      searchResults.textContent = '';
      const errorDiv = document.createElement('div');
      errorDiv.className = 'loading-row';
      errorDiv.textContent = 'Search error: ' + error.message;
      searchResults.appendChild(errorDiv);
    }
  }

  async function expandResult(element) {
    const container = element.querySelector('.expanded-container');
    if (container.querySelector('.expanded-view')) {
      container.innerHTML = '';
      return;
    }

    const key = element.dataset.key;
    const chunkId = parseInt(element.dataset.chunkId, 10);

    try {
      const response = await fetch(`/api/chunk/${encodeURIComponent(key)}/${chunkId}`);
      const chunk = await response.json();
      container.innerHTML = `
        <div class="expanded-view">
          <pre>${esc(chunk.text || chunk.error || 'No content')}</pre>
          <div class="actions">
            <button class="btn btn-sm btn-cyan" type="button" data-action="load-full" data-key="${esc(key)}">Load full memory</button>
            <button class="btn btn-sm" type="button" data-action="view-edit" data-key="${esc(key)}">View / Edit</button>
          </div>
        </div>
      `;
    } catch (error) {
      container.innerHTML = '<div class="expanded-view"><pre>Error loading chunk</pre></div>';
    }
  }

  async function loadFullMemory(key, button) {
    button.disabled = true;
    button.textContent = 'Loading...';
    try {
      const response = await fetch(`/api/memory/${encodeURIComponent(key)}`);
      const memory = await response.json();
      const view = button.closest('.expanded-view');
      view.querySelector('pre').textContent = memory.content || memory.error || 'No content';
      button.textContent = 'Loaded';
    } catch (error) {
      button.textContent = 'Error';
    }
  }

  function openCreateModal() {
    editMode = false;
    document.getElementById('modal-create-title').textContent = 'New Memory';
    document.getElementById('form-key').value = '';
    document.getElementById('form-key').disabled = false;
    document.getElementById('form-title').value = '';
    document.getElementById('form-tags').value = '';
    document.getElementById('form-content').value = '';
    document.getElementById('modal-create').classList.add('active');
  }

  function openEditModal(key, title, tags, content) {
    editMode = true;
    document.getElementById('modal-create-title').textContent = 'Edit Memory';
    document.getElementById('form-key').value = key;
    document.getElementById('form-key').disabled = true;
    document.getElementById('form-title').value = title;
    document.getElementById('form-tags').value = tags;
    document.getElementById('form-content').value = content;
    closeModal('modal-view');
    document.getElementById('modal-create').classList.add('active');
  }

  async function saveMemory() {
    const key = document.getElementById('form-key').value.trim();
    const title = document.getElementById('form-title').value.trim();
    const tags = document.getElementById('form-tags').value.trim();
    const content = document.getElementById('form-content').value;

    if (!key || !content) {
      alert('Key and content are required.');
      return;
    }

    const button = document.getElementById('btn-save');
    button.disabled = true;
    button.textContent = 'Saving...';

    try {
      const method = editMode ? 'PUT' : 'POST';
      const url = editMode ? `/api/memory/${encodeURIComponent(key)}` : '/api/memory';
      const response = await fetch(url, {
        method,
        headers: getWriteHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ key, title: title || key, tags, content }),
      });
      if (response.status === 409) {
        const duplicate = await response.json();
        const proceed = confirm(
          `Similar memory already exists:\n"${duplicate.existing_title}" (${(duplicate.score * 100).toFixed(0)}% similar)\n\nStore anyway?`
        );
        if (proceed) {
          const forcedResponse = await fetch(url, {
            method,
            headers: getWriteHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ key, title: title || key, tags, content, force: true }),
          });
          if (!forcedResponse.ok) {
            const errorBody = await forcedResponse.json();
            throw new Error(errorBody.error || 'Save failed');
          }
        }
        button.disabled = false;
        button.textContent = 'Save';
        if (proceed) {
          closeModal('modal-create');
          location.reload();
        }
        return;
      }
      if (!response.ok) {
        const errorBody = await response.json();
        throw new Error(errorBody.error || 'Save failed');
      }
      closeModal('modal-create');
      location.reload();
    } catch (error) {
      alert('Error: ' + error.message);
    } finally {
      button.disabled = false;
      button.textContent = 'Save';
    }
  }

  async function openViewModal(key) {
    currentViewKey = key;
    document.getElementById('view-title').textContent = 'Loading...';
    document.getElementById('view-meta').textContent = '';
    document.getElementById('view-tags').innerHTML = '';
    document.getElementById('view-content').textContent = 'Loading...';
    document.getElementById('modal-view').classList.add('active');
    document.getElementById('view-related').classList.add('hidden');
    document.getElementById('view-related-content').innerHTML = '';

    try {
      const response = await fetch(`/api/memory/${encodeURIComponent(key)}`);
      const memory = await response.json();
      if (memory.error) {
        document.getElementById('view-content').textContent = memory.error;
        return;
      }
      document.getElementById('view-title').textContent = memory.title || memory.key;
      const lastAccessed = memory.last_accessed ? memory.last_accessed.slice(0, 10) : 'never';
      document.getElementById('view-meta').textContent =
        `Key: ${memory.key} - Created: ${(memory.created_at || '').slice(0, 10)} - Updated: ${(memory.updated_at || '').slice(0, 10)} - Accessed: ${lastAccessed} - ${memory.chars || 0} chars`;
      document.getElementById('view-tags').innerHTML =
        (memory.tags || []).map(tag => `<span class="tag-chip">${esc(tag)}</span>`).join(' ');
      document.getElementById('view-content').textContent = memory.content || '';
      loadRelatedMemories(key);
    } catch (error) {
      document.getElementById('view-content').textContent = 'Error loading memory.';
    }
  }

  async function loadRelatedMemories(key) {
    try {
      const response = await fetch(`/api/related/${encodeURIComponent(key)}`);
      const data = await response.json();
      const related = [...(data.forward || []), ...(data.reverse || [])];
      const container = document.getElementById('view-related-content');
      const section = document.getElementById('view-related');
      if (!related.length) {
        section.classList.add('hidden');
        return;
      }
      section.classList.remove('hidden');
      container.innerHTML = related.map(memory => `
        <div class="related-link">
          <button class="related-link-button" type="button" data-action="open-related" data-key="${esc(memory.key)}">${esc(memory.title)}</button>
          <span>${esc(memory.key)}</span>
        </div>
      `).join('');
    } catch (error) {
      document.getElementById('view-related').classList.add('hidden');
    }
  }

  function editCurrentMemory() {
    const title = document.getElementById('view-title').textContent;
    const content = document.getElementById('view-content').textContent;
    const tagEls = document.getElementById('view-tags').querySelectorAll('.tag-chip');
    const tags = Array.from(tagEls).map(element => element.textContent).join(', ');
    openEditModal(currentViewKey, title, tags, content);
  }

  async function deleteCurrentMemory() {
    if (!confirm(`Delete memory "${currentViewKey}"? This cannot be undone.`)) return;
    try {
      const response = await fetch(`/api/memory/${encodeURIComponent(currentViewKey)}`, {
        method: 'DELETE',
        headers: getWriteHeaders(),
      });
      if (!response.ok) throw new Error(explainWriteAuthFailure(response));
      closeModal('modal-view');
      location.reload();
    } catch (error) {
      alert('Error: ' + error.message);
    }
  }

  function applyTemplate(type) {
    const templates = {
      project: '## Overview\n\n## Current Status\n\n## Key Decisions\n\n## Open Questions\n\n',
      decision: '## Context\n\n## Options Considered\n\n1. \n2. \n3. \n\n## Decision\n\n## Rationale\n\n## Consequences\n\n',
      reference: '## Source\n\n## Summary\n\n## How to Access\n\n## Related\n\n',
      snippet: '## Description\n\n## Code / Content\n\n```\n\n```\n\n## Usage Notes\n\n',
    };
    document.getElementById('form-content').value = templates[type] || '';
  }

  function closeModal(id) {
    if (!id) return;
    document.getElementById(id).classList.remove('active');
  }

  function esc(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
