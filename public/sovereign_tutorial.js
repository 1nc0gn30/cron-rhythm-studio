/**
 * Sovereign Reusable Tutorial & Braille/ASCII Guide (Safe DOM APIs, Dual-Theme)
 * Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform
 */
(function () {
  if (window.__SOVEREIGN_TUTORIAL_ATTACHED__) return;
  window.__SOVEREIGN_TUTORIAL_ATTACHED__ = true;

  window.createSovereignTutorial = function (config) {
    const { toolId, toolName, tagline, steps = [], accentColor = '#D4AF37' } = config || {};
    if (!toolId || document.getElementById(`sovTutorial-${toolId}`)) return;

    const modal = document.createElement('div');
    modal.id = `sovTutorial-${toolId}`;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', `${toolName || 'Tool'} quickstart guide`);
    modal.style.cssText =
      'display:none;position:fixed;inset:0;z-index:999999;background:rgba(4,6,12,0.78);' +
      'align-items:center;justify-content:center;padding:18px;box-sizing:border-box;';

    const card = document.createElement('div');
    card.style.cssText =
      'border-radius:18px;max-width:620px;width:100%;max-height:90vh;overflow-y:auto;' +
      'padding:24px;position:relative;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;box-sizing:border-box;';

    const closeBtn = document.createElement('button');
    closeBtn.id = `sovCloseBtn-${toolId}`;
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Close guide');
    closeBtn.textContent = '×';
    closeBtn.style.cssText =
      'position:absolute;top:14px;right:14px;min-width:44px;min-height:44px;border-radius:999px;' +
      'font-size:20px;cursor:pointer;font-weight:700;display:flex;align-items:center;justify-content:center;';

    const hdr = document.createElement('div');
    hdr.style.cssText = 'margin-bottom:14px;padding-right:52px;';
    const titleEl = document.createElement('h2');
    titleEl.textContent = String(toolName || '');
    titleEl.style.cssText = 'margin:0;font-size:18px;font-weight:800;letter-spacing:0.03em;';
    const tagEl = document.createElement('p');
    tagEl.textContent = String(tagline || '');
    tagEl.style.cssText = 'margin:4px 0 0;font-size:12px;';
    hdr.appendChild(titleEl);
    hdr.appendChild(tagEl);

    const brailleWrap = document.createElement('div');
    brailleWrap.style.cssText =
      'border-radius:10px;padding:10px;margin-bottom:16px;text-align:center;overflow:hidden;';
    const braillePre = document.createElement('pre');
    braillePre.id = `sovBrailleCanvas-${toolId}`;
    braillePre.style.cssText = 'font-size:10px;line-height:11px;margin:0;font-family:monospace;white-space:pre;';
    brailleWrap.appendChild(braillePre);

    const stepsWrap = document.createElement('div');
    stepsWrap.style.cssText = 'display:flex;flex-direction:column;gap:10px;';

    steps.forEach((s, idx) => {
      const row = document.createElement('div');
      row.className = 'sov-tut-step';
      row.style.cssText = 'display:flex;gap:12px;border-radius:10px;padding:12px;align-items:flex-start;';
      const ico = document.createElement('span');
      ico.textContent = String(s.icon || '•');
      ico.style.cssText = 'font-size:22px;line-height:1.1;';
      const body = document.createElement('div');
      const h4 = document.createElement('h4');
      h4.textContent = `Step ${idx + 1}: ${String(s.title || '')}`;
      h4.style.cssText = 'margin:0 0 4px;font-size:13px;font-weight:700;';
      const p = document.createElement('p');
      p.textContent = String(s.desc || '');
      p.style.cssText = 'margin:0;font-size:12px;line-height:1.5;';
      body.appendChild(h4);
      body.appendChild(p);
      row.appendChild(ico);
      row.appendChild(body);
      stepsWrap.appendChild(row);
    });

    const footer = document.createElement('div');
    footer.style.cssText =
      'margin-top:18px;display:flex;justify-content:flex-end;align-items:center;padding-top:12px;';
    const actionBtn = document.createElement('button');
    actionBtn.id = `sovActionBtn-${toolId}`;
    actionBtn.type = 'button';
    actionBtn.textContent = 'Close Guide';
    actionBtn.style.cssText =
      'min-height:44px;border:none;padding:10px 22px;border-radius:999px;font-weight:800;font-size:12px;cursor:pointer;';
    footer.appendChild(actionBtn);

    card.appendChild(closeBtn);
    card.appendChild(hdr);
    card.appendChild(brailleWrap);
    card.appendChild(stepsWrap);
    card.appendChild(footer);
    modal.appendChild(card);
    document.body.appendChild(modal);

    function applyTheme() {
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      card.style.background = isLight ? '#FFFFFF' : '#0D111E';
      card.style.color = isLight ? '#101828' : '#F8FAFC';
      card.style.border = `2px solid ${isLight ? '#9A6F0B' : accentColor}`;
      closeBtn.style.background = isLight ? '#F3EFE6' : 'rgba(255,255,255,0.08)';
      closeBtn.style.color = isLight ? '#101828' : '#F8FAFC';
      closeBtn.style.border = `1px solid ${isLight ? 'rgba(16,24,40,0.18)' : 'rgba(255,255,255,0.2)'}`;
      titleEl.style.color = isLight ? '#7A5808' : accentColor;
      tagEl.style.color = isLight ? '#475467' : '#94A3B8';
      brailleWrap.style.background = isLight ? '#F3EFE6' : '#05070D';
      brailleWrap.style.border = `1px solid ${isLight ? 'rgba(154,111,11,0.3)' : 'rgba(212,175,55,0.3)'}`;
      braillePre.style.color = isLight ? '#0369A1' : '#38BDF8';
      stepsWrap.querySelectorAll('.sov-tut-step').forEach((row) => {
        row.style.background = isLight ? '#FAF8F3' : 'rgba(255,255,255,0.03)';
        row.style.border = `1px solid ${isLight ? 'rgba(16,24,40,0.10)' : 'rgba(255,255,255,0.08)'}`;
      });
      actionBtn.style.background = isLight ? '#7A5808' : accentColor;
      actionBtn.style.color = isLight ? '#FFFFFF' : '#08080B';
    }

    let animInterval = null;
    let tick = 0;
    function renderBraille() {
      tick += 0.16;
      const W = 32;
      const H = 6;
      const dots = [
        [0, 0, 0x01], [0, 1, 0x02], [0, 2, 0x04], [0, 3, 0x40],
        [1, 0, 0x08], [1, 1, 0x10], [1, 2, 0x20], [1, 3, 0x80],
      ];
      let out = '';
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          let mask = 0;
          for (let d = 0; d < 8; d++) {
            const px = x * 2 + dots[d][0];
            const py = y * 4 + dots[d][1];
            if (Math.sin(px * 0.2 + tick) * Math.cos(py * 0.35 + tick) > 0.08) mask |= dots[d][2];
          }
          out += String.fromCharCode(0x2800 | mask);
        }
        out += '\n';
      }
      braillePre.textContent = out;
    }

    function openModal() {
      applyTheme();
      modal.style.display = 'flex';
      renderBraille();
      if (!animInterval) animInterval = setInterval(renderBraille, 65);
    }

    function closeModal() {
      modal.style.display = 'none';
      if (animInterval) {
        clearInterval(animInterval);
        animInterval = null;
      }
    }

    closeBtn.addEventListener('click', closeModal);
    actionBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });

    return { open: openModal, close: closeModal };
  };
})();
