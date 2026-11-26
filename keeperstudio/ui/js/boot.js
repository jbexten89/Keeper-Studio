// Keeper Studio UI — boot. Plain scripts sharing one global scope, loaded in order by index.html.
'use strict';
/* ================= Boot ================= */
async function init() {
  buildFilterBar(); buildToolbar(); buildLoupe(); buildCompare(); buildHelp();
  bindEvents(); bindModuleEvents();
  renderAll();
  window.reveal = reveal;
  if (location.search.includes('fallback')) S.banners.push({ id: 'fallback', text: 'Keeper Studio opened in your web browser because its own window couldn’t start. Everything works here, but folder pickers ask you to type or paste the path.' });
  try { const h = await api('/api/hello', {}); S.recent = h.recent || []; S.hello = h; } catch (e) { toast('Keeper Studio’s engine is not responding: ' + esc(e.message), 6000); }
  { const hv = $('#help .help-ver'); if (hv && S.hello) hv.textContent = 'Keeper Studio ' + S.hello.version; }
  setTimeout(checkForUpdate, 4000);
  await Promise.all([loadStore(), Crop.load(), Comp.load(), Ord.load()]);
  renderAll();
}
init();

// Small hook for automated testing / power users
window.KeeperStudio = { loadFolder, state: S, Crop, Comp, Cut, Ret, Ord };
