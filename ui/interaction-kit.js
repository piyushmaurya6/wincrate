/*
 * better-design · interaction kit (JS, no dependencies)
 */
(function (root) {
  'use strict';

  var MIN_PRESS_MS = 90;
  var reduceMq = root.matchMedia ? root.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  var clamp = function (v, a, b) { return v < a ? a : v > b ? b : v; };
  var PRESSABLE = '.ui-press, .ui-switch, .ui-check';

  function disabled(el) { return el.disabled || el.getAttribute('aria-disabled') === 'true'; }

  function pressScale(el) {
    if (el.classList.contains('ui-press--surface')) return 0.988;
    var r = el.getBoundingClientRect();
    return clamp(1 - 8 / (r.width + r.height), 0.92, 0.985).toFixed(4);
  }

  function pressOn(el, x, y) {
    if (disabled(el)) return;
    var r = el.getBoundingClientRect();
    el.style.setProperty('--ui-press-scale', pressScale(el));
    if (x != null && r.width > 0 && r.height > 0) {
      el.style.setProperty('--ui-px', ((x - r.left) / r.width * 100).toFixed(1) + '%');
      el.style.setProperty('--ui-py', ((y - r.top) / r.height * 100).toFixed(1) + '%');
    } else {
      el.style.setProperty('--ui-px', '50%');
      el.style.setProperty('--ui-py', '50%');
    }
    el._uiPressAt = performance.now();
    clearTimeout(el._uiPressTimer);
    el.setAttribute('data-pressed', '');
  }

  function pressOff(el) {
    if (!el || !el.hasAttribute('data-pressed')) return;
    var held = performance.now() - (el._uiPressAt || 0);
    var wait = Math.max(0, MIN_PRESS_MS - held);
    clearTimeout(el._uiPressTimer);
    el._uiPressTimer = setTimeout(function () { el.removeAttribute('data-pressed'); }, wait);
  }

  function init(scope) {
    scope = scope || document;
    var active = null;
    function down(e) {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      var el = e.target.closest && e.target.closest(PRESSABLE);
      if (!el || !scope.contains(el)) return;
      active = el;
      pressOn(el, e.clientX, e.clientY);
    }
    function up() { pressOff(active); active = null; }
    function key(e) {
      if (e.repeat) return;
      var el = e.target.closest && e.target.closest(PRESSABLE);
      if (!el) return;
      if (e.key === ' ' || e.key === 'Enter') {
        if (e.type === 'keydown') pressOn(el); else pressOff(el);
      }
    }
    scope.addEventListener('pointerdown', down, { passive: true });
    root.addEventListener('pointerup', up, { passive: true });
    root.addEventListener('pointercancel', up, { passive: true });
    scope.addEventListener('keydown', key);
    scope.addEventListener('keyup', key);
    scope.addEventListener('focusout', function (e) {
      var el = e.target.closest && e.target.closest(PRESSABLE);
      if (el) pressOff(el);
    });
  }

  function segmented(el, opts) {
    var o = Object.assign({ onChange: null }, opts || {});
    el.classList.add('ui-segmented');
    var ind = document.createElement('span');
    ind.className = 'ui-segmented__indicator';
    ind.setAttribute('aria-hidden', 'true');
    el.insertBefore(ind, el.firstChild);
    var items = Array.prototype.slice.call(el.querySelectorAll(':scope > button'));
    var attr = items[0] && items[0].hasAttribute('aria-pressed') ? 'aria-pressed' : 'aria-selected';

    function place(animate) {
      var cur = items.filter(function (b) { return b.getAttribute(attr) === 'true'; })[0] || items[0];
      if (!cur) return;
      if (!animate) ind.style.transition = 'none';
      el.style.setProperty('--ui-seg-x', cur.offsetLeft + 'px');
      el.style.setProperty('--ui-seg-w', cur.offsetWidth + 'px');
      if (!animate) { void ind.offsetWidth; ind.style.transition = ''; }
    }
    function select(b, notify) {
      items.forEach(function (x) {
        x.setAttribute(attr, String(x === b));
        if (attr === 'aria-selected') x.tabIndex = x === b ? 0 : -1;
      });
      place(true);
      if (notify !== false && o.onChange) o.onChange(items.indexOf(b), b);
    }
    items.forEach(function (b) { b.addEventListener('click', function () { select(b, true); }); });
    el.addEventListener('keydown', function (e) {
      var d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return;
      var i = items.findIndex(function (x) { return x.getAttribute(attr) === 'true'; });
      var n = items[(i + d + items.length) % items.length];
      e.preventDefault();
      select(n, true);
      n.focus();
    });
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(function () { place(false); }).observe(el);
    }
    place(false);
    return {
      select: function (i, notify) { if (items[i]) select(items[i], notify); }
    };
  }

  function shake(el) {
    if (!el || reduceMq.matches) return;
    el.classList.remove('ui-shake');
    void el.offsetWidth;
    el.classList.add('ui-shake');
    el.addEventListener('animationend', function () { el.classList.remove('ui-shake'); }, { once: true });
  }

  var api = root.BetterUI = root.BetterUI || {};
  api.init = init;
  api.segmented = segmented;
  api.shake = shake;
})(typeof globalThis !== 'undefined' ? globalThis : window);
