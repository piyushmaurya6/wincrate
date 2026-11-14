/*
 * WinCrate UI Controller
 */
(function () {
  'use strict';

  var SVG_BOX = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>';
  var SVG_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>';
  var SVG_WARN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
  var SVG_FOLDER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>';

  var state = {
    apps: [],
    filter: 'packable',
    query: '',
    selectedId: null,
    selectedDetails: null,
    outputDir: '',
    outputFreeBytes: 0,
    packages: [],
    activeJobId: null,
    pollTimer: null
  };

  var els = {
    searchInput: document.getElementById('search-input'),
    filterTabs: document.getElementById('filter-tabs'),
    outputDirBtn: document.getElementById('output-dir-btn'),
    outputDirText: document.getElementById('output-dir-text'),
    outputFreeText: document.getElementById('output-free-text'),
    refreshBtn: document.getElementById('refresh-btn'),
    queueCount: document.getElementById('queue-count'),
    appList: document.getElementById('app-list'),
    dropZone: document.getElementById('drop-zone'),
    dropZoneError: document.getElementById('drop-zone-error'),
    chooseCustomBtn: document.getElementById('choose-custom-btn'),

    wbStatusChip: document.getElementById('wb-status-chip'),
    wbLoading: document.getElementById('wb-loading'),
    wbEmpty: document.getElementById('wb-empty'),
    wbContent: document.getElementById('wb-content'),
    wbFooter: document.getElementById('wb-footer'),
    wbException: document.getElementById('wb-exception'),
    wbExceptionText: document.getElementById('wb-exception-text'),
    wbPickLocBtn: document.getElementById('wb-pick-loc-btn'),
    wbError: document.getElementById('wb-error'),
    wbErrorText: document.getElementById('wb-error-text'),

    wbIconBox: document.getElementById('wb-icon-box'),
    wbAppTitle: document.getElementById('wb-app-title'),
    wbAppSub: document.getElementById('wb-app-sub'),
    inpPkgName: document.getElementById('inp-pkg-name'),
    inpPkgVersion: document.getElementById('inp-pkg-version'),
    selMainExe: document.getElementById('sel-main-exe'),

    ledFolderPath: document.getElementById('led-folder-path'),
    ledFolderSize: document.getElementById('led-folder-size'),
    changeAppFolderBtn: document.getElementById('change-app-folder-btn'),
    ledFilesDesc: document.getElementById('led-files-desc'),
    ledShortcutsCount: document.getElementById('led-shortcuts-count'),
    ledRegCount: document.getElementById('led-reg-count'),

    swAppData: document.getElementById('sw-appdata'),
    appdataFact: document.getElementById('appdata-fact'),
    chkRowCache: document.getElementById('chk-row-cache'),
    chkExcludeCache: document.getElementById('chk-exclude-cache'),
    chkRegistry: document.getElementById('chk-registry'),
    chkDesktop: document.getElementById('chk-desktop'),
    chkStartMenu: document.getElementById('chk-startmenu'),

    progressBox: document.getElementById('progress-box'),
    progressMsg: document.getElementById('progress-msg'),
    progressPct: document.getElementById('progress-pct'),
    progressFill: document.getElementById('progress-fill'),
    inpOutFile: document.getElementById('inp-out-file'),
    cancelBuildBtn: document.getElementById('cancel-build-btn'),
    buildBtn: document.getElementById('build-btn'),
    buildBtnLabel: document.getElementById('build-btn-label'),

    openOutputBtn: document.getElementById('open-output-btn'),
    crateList: document.getElementById('crate-list')
  };

  function formatBytes(bytes) {
    var b = Number(bytes || 0);
    if (b <= 0) return '0 B';
    if (b < 1024) return b + ' B';
    var kb = b / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    var mb = kb / 1024;
    if (mb < 1024) return mb.toFixed(1) + ' MB';
    var gb = mb / 1024;
    return gb.toFixed(2) + ' GB';
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderStatusChip(readiness) {
    if (readiness === 'ready') {
      return '<span class="status-chip status-chip--ready" data-ui-group="chip">' + SVG_CHECK + '<span>Packable</span></span>';
    }
    if (readiness === 'service_warning') {
      return '<span class="status-chip status-chip--warn" data-ui-group="chip">' + SVG_WARN + '<span>Service warning</span></span>';
    }
    return '<span class="status-chip status-chip--manual" data-ui-group="chip">' + SVG_FOLDER + '<span>Manual folder</span></span>';
  }

  function apiGet(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
        return d;
      });
    });
  }

  function apiPost(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
        return d;
      });
    });
  }

  function updateOutputBar() {
    els.outputDirText.textContent = state.outputDir || 'Select output folder';
    els.outputDirBtn.title = 'Output directory: ' + (state.outputDir || '') + ' (click to change)';
    els.outputFreeText.textContent = state.outputFreeBytes > 0
      ? (formatBytes(state.outputFreeBytes) + ' free')
      : '';
  }

  function renderPackages() {
    if (!state.packages || state.packages.length === 0) {
      els.crateList.innerHTML =
        '<div class="empty-box">' +
        '<strong>No .exe packages built yet</strong>' +
        '<span>Standalone Setup .exe files you build appear here ready to copy to another Windows PC.</span>' +
        '</div>';
      return;
    }
    els.crateList.innerHTML = state.packages.map(function (pkg) {
      return (
        '<div class="crate-item">' +
          '<div class="crate-item__name">' + escapeHtml(pkg.filename) + '</div>' +
          '<div class="crate-item__bottom">' +
            '<span class="crate-item__size">' + formatBytes(pkg.bytes) + '</span>' +
            '<button type="button" class="btn btn--sm btn--secondary ui-press ui-focus" data-reveal="' + escapeHtml(pkg.path) + '"><span>Show in Explorer</span></button>' +
          '</div>' +
        '</div>'
      );
    }).join('');
  }

  function getFilteredApps() {
    var q = state.query.trim().toLowerCase();
    return state.apps.filter(function (app) {
      if (state.filter === 'packable' && app.readiness === 'manual_folder') return false;
      if (!q) return true;
      return (
        app.name.toLowerCase().indexOf(q) !== -1 ||
        app.publisher.toLowerCase().indexOf(q) !== -1 ||
        (app.install_location && app.install_location.toLowerCase().indexOf(q) !== -1)
      );
    });
  }

  var lastRenderedIds = '';

  function renderAppList() {
    var filtered = getFilteredApps();
    els.queueCount.textContent = filtered.length + ' of ' + state.apps.length;

    if (filtered.length === 0) {
      lastRenderedIds = '';
      els.appList.innerHTML =
        '<div class="empty-box">' +
        '<strong>No matching software</strong>' +
        '<span>Clear the filter or switch to "All installed" to inspect entries without a Registry path.</span>' +
        '</div>';
      return;
    }

    var nextIds = filtered.map(function (a) { return a.id; }).join(',');
    if (nextIds === lastRenderedIds) {
      var byId = {};
      filtered.forEach(function (a) { byId[a.id] = a; });
      var rows = els.appList.querySelectorAll('[data-app-id]');
      if (rows.length === filtered.length) {
        rows.forEach(function (row) {
          var id = row.getAttribute('data-app-id');
          var app = byId[id];
          if (!app) return;
          row.setAttribute('aria-selected', id === state.selectedId ? 'true' : 'false');
          var szEl = row.querySelector('.app-row__size');
          if (szEl) szEl.textContent = app.estimated_bytes > 0 ? formatBytes(app.estimated_bytes) : '—';
        });
        return;
      }
    }

    lastRenderedIds = nextIds;
    els.appList.innerHTML = filtered.map(function (app) {
      var selected = app.id === state.selectedId;
      var iconHtml = app.icon
        ? '<img src="' + app.icon + '" alt="">'
        : SVG_BOX;
      var sizeStr = app.estimated_bytes > 0 ? formatBytes(app.estimated_bytes) : '—';
      return (
        '<button type="button" role="option" data-ui-align="start" class="app-row ui-press ui-press--surface ui-focus" ' +
          'aria-selected="' + (selected ? 'true' : 'false') + '" data-app-id="' + escapeHtml(app.id) + '">' +
          '<span class="app-row__icon">' + iconHtml + '</span>' +
          '<span class="app-row__main">' +
            '<span class="app-row__name">' + escapeHtml(app.name) + '</span>' +
            '<span class="app-row__meta">' + escapeHtml(app.publisher) + ' (' + escapeHtml(app.version) + ')</span>' +
          '</span>' +
          '<span class="app-row__right">' +
            renderStatusChip(app.readiness) +
            '<span class="app-row__size">' + sizeStr + '</span>' +
          '</span>' +
        '</button>'
      );
    }).join('');
  }

  function setChecked(btnEl, val) {
    btnEl.setAttribute('aria-checked', val ? 'true' : 'false');
  }

  function isChecked(btnEl) {
    return btnEl.getAttribute('aria-checked') === 'true';
  }

  function updateAppDataSummary() {
    var d = state.selectedDetails;
    if (!d || !d.appdata) return;
    var ad = d.appdata;
    if (!ad.found) {
      els.swAppData.disabled = true;
      setChecked(els.swAppData, false);
      els.chkExcludeCache.disabled = true;
      els.chkRowCache.setAttribute('aria-disabled', 'true');
      els.appdataFact.textContent = 'No matching folders detected in %APPDATA% or %LOCALAPPDATA%.';
      return;
    }

    els.swAppData.disabled = false;
    var inc = isChecked(els.swAppData);
    els.chkExcludeCache.disabled = !inc;
    els.chkRowCache.setAttribute('aria-disabled', inc ? 'false' : 'true');

    var excl = isChecked(els.chkExcludeCache);
    var activeBytes = excl ? ad.clean_bytes : ad.total_bytes;
    var paths = ad.folders.map(function (f) { return f.scope + '\\' + f.rel_path; }).join(', ');

    if (inc) {
      els.appdataFact.textContent =
        'Adds ' + formatBytes(activeBytes) + ' from ' + paths +
        (excl && ad.cache_bytes > 0 ? ' (' + formatBytes(ad.cache_bytes) + ' cache omitted)' : '');
    } else {
      els.appdataFact.textContent =
        'Available: ' + formatBytes(ad.clean_bytes) + ' config in ' + paths +
        (ad.cache_bytes > 0 ? ' (+ ' + formatBytes(ad.cache_bytes) + ' cache)' : '');
    }
  }

  function renderWorkbench(details) {
    state.selectedDetails = details;
    els.wbLoading.hidden = true;
    els.wbEmpty.hidden = true;
    els.wbContent.hidden = false;
    els.wbFooter.hidden = false;
    els.wbError.hidden = true;

    els.wbStatusChip.innerHTML = renderStatusChip(details.readiness);

    if (details.readiness === 'service_warning' || details.readiness === 'manual_folder') {
      els.wbException.hidden = false;
      els.wbExceptionText.textContent = details.readiness_detail;
      els.wbPickLocBtn.hidden = details.readiness !== 'manual_folder';
    } else {
      els.wbException.hidden = true;
    }

    els.wbIconBox.innerHTML = details.icon
      ? '<img src="' + details.icon + '" alt="">'
      : SVG_BOX;
    els.wbAppTitle.textContent = details.name;
    els.wbAppSub.textContent = details.publisher + '  |  Version ' + details.version;

    els.inpPkgName.value = details.name;
    els.inpPkgVersion.value = details.version;
    els.inpOutFile.value = details.default_output_filename;

    var exes = details.exe_candidates || [];
    if (exes.length === 0) {
      els.selMainExe.innerHTML = '<option value="">No launcher .exe detected (files only)</option>';
    } else {
      els.selMainExe.innerHTML = exes.map(function (rel) {
        var sel = rel === details.selected_main_exe ? ' selected' : '';
        return '<option value="' + escapeHtml(rel) + '"' + sel + '>' + escapeHtml(rel) + '</option>';
      }).join('');
    }

    var hasLoc = Boolean(details.install_location && details.file_count > 0);
    els.ledFolderPath.textContent = details.install_location || 'Folder not set';
    els.ledFolderPath.title = details.install_location || '';
    els.ledFolderSize.textContent = hasLoc ? formatBytes(details.app_bytes) : '—';
    els.ledFilesDesc.textContent = hasLoc
      ? (details.file_count.toLocaleString() + ' files ready to compress')
      : 'Select the application folder to inspect files';
    els.ledShortcutsCount.textContent = details.shortcuts_count + ' detected shortcuts';
    els.ledRegCount.textContent = details.registry_key_count + ' keys';

    setChecked(els.swAppData, false);
    setChecked(els.chkExcludeCache, true);
    setChecked(els.chkRegistry, details.registry_key_count > 0);
    els.chkRegistry.disabled = details.registry_key_count === 0;
    setChecked(els.chkDesktop, exes.length > 0);
    setChecked(els.chkStartMenu, true);

    updateAppDataSummary();
    els.buildBtn.disabled = !hasLoc || Boolean(state.activeJobId);
  }

  function selectApp(appId, overrideFolder) {
    state.selectedId = appId;
    renderAppList();

    els.wbEmpty.hidden = true;
    els.wbContent.hidden = true;
    els.wbFooter.hidden = true;
    els.wbLoading.hidden = false;

    var url = '/api/inspect?id=' + encodeURIComponent(appId);
    if (overrideFolder) url += '&folder=' + encodeURIComponent(overrideFolder);

    apiGet(url)
      .then(function (details) {
        // Sync updated readiness/size back to summary list
        state.apps.forEach(function (a) {
          if (a.id === details.id) {
            a.install_location = details.install_location;
            a.readiness = details.readiness;
            a.estimated_bytes = details.app_bytes;
          }
        });
        renderAppList();
        renderWorkbench(details);
      })
      .catch(function (err) {
        els.wbLoading.hidden = true;
        els.wbContent.hidden = false;
        els.wbError.hidden = false;
        els.wbErrorText.textContent = err.message;
      });
  }

  function loadApps(forceRefresh) {
    els.refreshBtn.disabled = true;
    apiGet('/api/apps' + (forceRefresh ? '?refresh=1' : ''))
      .then(function (res) {
        state.apps = res.apps || [];
        state.outputDir = res.output_dir || '';
        state.outputFreeBytes = res.output_free_bytes || 0;
        state.packages = res.packages || [];
        updateOutputBar();
        renderPackages();
        renderAppList();

        var filtered = getFilteredApps();
        if (filtered.length > 0) {
          var keep = filtered.some(function (a) { return a.id === state.selectedId; });
          selectApp(keep ? state.selectedId : filtered[0].id);
        } else {
          els.wbLoading.hidden = true;
          els.wbContent.hidden = true;
          els.wbFooter.hidden = true;
          els.wbEmpty.hidden = false;
        }
      })
      .catch(function (err) {
        els.appList.innerHTML =
          '<div class="empty-box" role="alert">' +
          '<strong>Could not scan installed software</strong>' +
          '<span>' + escapeHtml(err.message) + '</span>' +
          '</div>';
      })
      .finally(function () {
        els.refreshBtn.disabled = false;
      });
  }

  function handleCustomFolderPath(folderOrExePath) {
    els.dropZoneError.hidden = true;
    els.dropZone.removeAttribute('data-drag-state');
    apiPost('/api/custom-folder', { path: folderOrExePath })
      .then(function (res) {
        var sum = res.summary;
        state.apps = state.apps.filter(function (a) { return a.id !== sum.id; });
        state.apps.unshift(sum);
        state.selectedId = sum.id;
        renderAppList();
        renderWorkbench(res.details);
      })
      .catch(function (err) {
        els.dropZone.setAttribute('data-drag-state', 'reject');
        els.dropZoneError.textContent = err.message;
        els.dropZoneError.hidden = false;
        BetterUI.shake(els.dropZone);
        setTimeout(function () {
          if (els.dropZone.getAttribute('data-drag-state') === 'reject') {
            els.dropZone.removeAttribute('data-drag-state');
          }
        }, 2200);
      });
  }

  // Expose hook for pywebview native full-path drop
  window.WinCrateHandleNativeDrop = function (fullPath) {
    document.body.removeAttribute('data-window-drag');
    els.dropZone.removeAttribute('data-drag-state');
    if (fullPath) handleCustomFolderPath(fullPath);
  };

  function startBuild() {
    if (!state.selectedDetails || state.activeJobId) return;
    els.wbError.hidden = true;

    var payload = {
      app_id: state.selectedDetails.id,
      package_name: els.inpPkgName.value.trim() || state.selectedDetails.name,
      package_version: els.inpPkgVersion.value.trim() || state.selectedDetails.version,
      publisher: state.selectedDetails.publisher,
      install_location: state.selectedDetails.install_location,
      main_exe_rel: els.selMainExe.value,
      output_dir: state.outputDir,
      output_filename: els.inpOutFile.value.trim() || state.selectedDetails.default_output_filename,
      include_appdata: isChecked(els.swAppData),
      exclude_appdata_cache: isChecked(els.chkExcludeCache),
      include_registry: isChecked(els.chkRegistry),
      desktop_shortcut: isChecked(els.chkDesktop),
      start_menu_shortcut: isChecked(els.chkStartMenu),
      register_uninstaller: isChecked(els.chkStartMenu)
    };

    els.buildBtn.disabled = true;
    els.cancelBuildBtn.hidden = false;
    els.progressBox.hidden = false;
    els.progressFill.style.width = '3%';
    els.progressPct.textContent = '3%';
    els.progressMsg.textContent = 'Starting compiler & packager...';

    apiPost('/api/build', payload)
      .then(function (job) {
        state.activeJobId = job.job_id;
        pollBuildStatus();
      })
      .catch(function (err) {
        finishBuildUi();
        els.wbError.hidden = false;
        els.wbErrorText.textContent = err.message;
        BetterUI.shake(els.buildBtn);
      });
  }

  function pollBuildStatus() {
    if (!state.activeJobId) return;
    clearTimeout(state.pollTimer);
    apiGet('/api/build/status?job_id=' + encodeURIComponent(state.activeJobId))
      .then(function (job) {
        els.progressFill.style.width = job.percent + '%';
        els.progressPct.textContent = job.percent + '%';
        els.progressMsg.textContent = job.message;

        if (job.status === 'running') {
          state.pollTimer = setTimeout(pollBuildStatus, 250);
          return;
        }

        if (job.status === 'done') {
          state.activeJobId = null;
          els.cancelBuildBtn.hidden = true;
          els.buildBtn.disabled = false;
          els.progressFill.style.width = '100%';
          els.progressPct.textContent = '100%';
          els.progressMsg.textContent =
            'Saved ' + formatBytes(job.output_bytes) + ' standalone .exe (' + job.files_packed + ' files packed)';
          if (job.packages) {
            state.packages = job.packages;
            renderPackages();
          }
          apiGet('/api/packages').then(function (p) {
            state.outputFreeBytes = p.output_free_bytes || state.outputFreeBytes;
            state.packages = p.packages || state.packages;
            updateOutputBar();
            renderPackages();
          });
        } else if (job.status === 'cancelled') {
          finishBuildUi();
          els.progressBox.hidden = false;
          els.progressMsg.textContent = 'Build cancelled.';
          els.progressPct.textContent = '';
          els.progressFill.style.width = '0%';
        } else {
          finishBuildUi();
          els.wbError.hidden = false;
          els.wbErrorText.textContent = job.error || job.message;
          BetterUI.shake(els.buildBtn);
        }
      })
      .catch(function (err) {
        finishBuildUi();
        els.wbError.hidden = false;
        els.wbErrorText.textContent = err.message;
      });
  }

  function finishBuildUi() {
    state.activeJobId = null;
    clearTimeout(state.pollTimer);
    els.cancelBuildBtn.hidden = true;
    els.buildBtn.disabled = false;
    els.progressBox.hidden = true;
  }

  function bindEvents() {
    BetterUI.init(document);

    BetterUI.segmented(els.filterTabs, {
      onChange: function (idx, btn) {
        state.filter = btn.getAttribute('data-filter') || 'packable';
        renderAppList();
      }
    });

    els.searchInput.addEventListener('input', function () {
      state.query = els.searchInput.value;
      renderAppList();
    });

    window.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        els.searchInput.focus();
        els.searchInput.select();
      }
    });

    els.refreshBtn.addEventListener('click', function () {
      loadApps(true);
    });

    els.outputDirBtn.addEventListener('click', function () {
      apiPost('/api/pick-folder', { kind: 'output', initial_dir: state.outputDir })
        .then(function (res) {
          if (!res.cancelled && res.path) {
            state.outputDir = res.path;
            state.outputFreeBytes = res.output_free_bytes || 0;
            state.packages = res.packages || [];
            updateOutputBar();
            renderPackages();
          }
        });
    });

    els.openOutputBtn.addEventListener('click', function () {
      if (state.outputDir) apiPost('/api/reveal', { path: state.outputDir });
    });

    els.appList.addEventListener('click', function (e) {
      var row = e.target.closest('[data-app-id]');
      if (!row) return;
      var id = row.getAttribute('data-app-id');
      if (id && id !== state.selectedId) selectApp(id);
    });

    els.crateList.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-reveal]');
      if (!btn) return;
      apiPost('/api/reveal', { path: btn.getAttribute('data-reveal') });
    });

    function browseForAppFolder(forSelectedApp) {
      var initDir = (forSelectedApp && state.selectedDetails && state.selectedDetails.install_location) || '';
      apiPost('/api/pick-folder', { kind: 'app', initial_dir: initDir })
        .then(function (res) {
          if (res.cancelled || !res.path) return;
          if (forSelectedApp && state.selectedId) {
            selectApp(state.selectedId, res.path);
          } else {
            handleCustomFolderPath(res.path);
          }
        });
    }

    els.chooseCustomBtn.addEventListener('click', function () { browseForAppFolder(false); });
    els.changeAppFolderBtn.addEventListener('click', function () { browseForAppFolder(true); });
    els.wbPickLocBtn.addEventListener('click', function () { browseForAppFolder(true); });

    // Switch & Checkbox toggles
    els.swAppData.addEventListener('click', function () {
      if (els.swAppData.disabled) return;
      setChecked(els.swAppData, !isChecked(els.swAppData));
      updateAppDataSummary();
    });

    [els.chkExcludeCache, els.chkRegistry, els.chkDesktop, els.chkStartMenu].forEach(function (chk) {
      chk.parentElement.addEventListener('click', function (e) {
        if (chk.disabled) return;
        if (e.target !== chk) chk.focus();
        setChecked(chk, !isChecked(chk));
        if (chk === els.chkExcludeCache) updateAppDataSummary();
      });
    });

    els.buildBtn.addEventListener('click', startBuild);
    els.cancelBuildBtn.addEventListener('click', function () {
      if (state.activeJobId) apiPost('/api/build/cancel', { job_id: state.activeJobId });
    });

    // Window & Drop Zone Drag Handling (prevents accidental navigation on off-target drop)
    var dragDepth = 0;
    window.addEventListener('dragenter', function (e) {
      e.preventDefault();
      dragDepth++;
      document.body.setAttribute('data-window-drag', 'true');
    });
    window.addEventListener('dragover', function (e) {
      e.preventDefault();
    });
    window.addEventListener('dragleave', function (e) {
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) document.body.removeAttribute('data-window-drag');
    });
    window.addEventListener('drop', function (e) {
      e.preventDefault();
      dragDepth = 0;
      document.body.removeAttribute('data-window-drag');
      els.dropZone.removeAttribute('data-drag-state');
    });

    var zoneDepth = 0;
    els.dropZone.addEventListener('dragenter', function (e) {
      e.preventDefault();
      e.stopPropagation();
      zoneDepth++;
      els.dropZoneError.hidden = true;
      els.dropZone.setAttribute('data-drag-state', 'over');
    });
    els.dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.stopPropagation();
    });
    els.dropZone.addEventListener('dragleave', function (e) {
      e.stopPropagation();
      zoneDepth = Math.max(0, zoneDepth - 1);
      if (zoneDepth === 0) els.dropZone.removeAttribute('data-drag-state');
    });
    els.dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      e.stopPropagation();
      zoneDepth = 0;
      dragDepth = 0;
      document.body.removeAttribute('data-window-drag');
      els.dropZone.removeAttribute('data-drag-state');

      // In standard Chromium (non-pywebview), File objects do not expose full OS paths;
      // check if path property exists or guide user to Choose folder when running in plain browser.
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length > 0) {
        var f = files[0];
        var full = f.path || f.pywebviewFullPath || '';
        if (full) {
          handleCustomFolderPath(full);
          return;
        }
        var fname = (f.name || '').toLowerCase();
        if (fname.indexOf('.') !== -1 && !fname.endsWith('.exe')) {
          els.dropZone.setAttribute('data-drag-state', 'reject');
          els.dropZoneError.textContent = 'Unsupported file "' + f.name + '". Drop an application folder or .exe file.';
          els.dropZoneError.hidden = false;
          BetterUI.shake(els.dropZone);
          return;
        }
      }
    });
  }

  bindEvents();
  loadApps(false);
})();
