// static/js/admin.js
document.addEventListener('DOMContentLoaded', () => {
  const adminTable = document.getElementById('admin-table');
  if (!adminTable) return;

  // --- Bulk selection ---
  const selectAllChk = document.getElementById('select-all');
  const itemChks = () => adminTable.querySelectorAll('.select-item');
  const selectedIds = () => Array.from(itemChks()).filter(cb => cb.checked).map(cb => cb.value);

  selectAllChk?.addEventListener('change', () => {
    itemChks().forEach(cb => cb.checked = selectAllChk.checked);
    updateSelectionCount();
  });
  adminTable.addEventListener('change', (e) => {
    if (e.target.classList.contains('select-item')) updateSelectionCount();
  });
  function updateSelectionCount() {
    const count = selectedIds().length;
    document.getElementById('selected-count').textContent = count ? `${count} selected` : '';
    document.getElementById('apply-bulk').disabled = !count;
    // If not all selected, uncheck selectAll, else check
    const chks = itemChks();
    selectAllChk.checked = chks.length && Array.from(chks).every(cb => cb.checked);
  }

  // --- Bulk Actions ---
  document.getElementById('apply-bulk')?.addEventListener('click', async (e) => {
    e.preventDefault();
    const action = document.getElementById('bulk-action').value;
    const ids = selectedIds();
    if (!action || !ids.length) return;
    if (!confirm(`Are you sure you want to ${action} ${ids.length} item(s)?`)) return;
    setActionWorking(true);
    try {
      const res = await fetch(`/admin/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ids })
      });
      if (!res.ok) throw new Error(await res.text());
      alert(`Bulk ${action} applied to ${ids.length} item(s).`);
      window.location.reload();
    } catch (err) {
      alert(`Bulk action failed: ${err}`);
    } finally {
      setActionWorking(false);
    }
  });

  function setActionWorking(working) {
    document.getElementById('apply-bulk').disabled = working;
    document.getElementById('bulk-action').disabled = working;
    adminTable.querySelectorAll('button, input[type="checkbox"]').forEach(el => el.disabled = working);
  }

  // --- Retry All Stuck ---
  document.getElementById('retry-stuck')?.addEventListener('click', async () => {
    if (!confirm("Retry all stuck items?")) return;
    try {
      const res = await fetch(`/admin/retry-stuck`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      alert('Retry enqueued for all stuck items.');
      window.location.reload();
    } catch (err) {
      alert(`Retry all failed: ${err}`);
    }
  });

  // --- Per-row actions ---
  adminTable.addEventListener('click', async (e) => {
    if (e.target.matches('.reprocess-btn')) {
      e.preventDefault();
      const id = e.target.dataset.id;
      if (!confirm(`Reprocess item ${id}?`)) return;
      try {
        e.target.disabled = true;
        const res = await fetch(`/admin/reprocess/${id}`, { method: 'POST' });
        if (!res.ok) throw new Error(await res.text());
        alert('Reprocess triggered.');
        window.location.reload();
      } catch (err) {
        alert('Reprocess failed: ' + err);
      } finally {
        e.target.disabled = false;
      }
    }
    if (e.target.matches('.delete-btn')) {
      e.preventDefault();
      const id = e.target.dataset.id;
      if (!confirm(`Delete item ${id}? This cannot be undone.`)) return;
      try {
        e.target.disabled = true;
        const res = await fetch(`/admin/delete/${id}`, { method: 'POST' });
        if (!res.ok) throw new Error(await res.text());
        alert('Delete triggered.');
        window.location.reload();
      } catch (err) {
        alert('Delete failed: ' + err);
      } finally {
        e.target.disabled = false;
      }
    }
    if (e.target.matches('.retry-btn')) {
      e.preventDefault();
      const id = e.target.dataset.id;
      try {
        e.target.disabled = true;
        const res = await fetch(`/admin/retry/${id}`, { method: 'POST' });
        if (!res.ok) throw new Error(await res.text());
        alert('Retry triggered.');
        window.location.reload();
      } catch (err) {
        alert('Retry failed: ' + err);
      } finally {
        e.target.disabled = false;
      }
    }
  });

  // --- Pagination ---
  document.getElementById('prev-page')?.addEventListener('click', () => {
    const page = parseInt(document.getElementById('current-page').textContent);
    if (page > 1) gotoPage(page - 1);
  });
  document.getElementById('next-page')?.addEventListener('click', () => {
    const page = parseInt(document.getElementById('current-page').textContent);
    gotoPage(page + 1);
  });
  function gotoPage(page) {
    const url = new URL(window.location.href);
    url.searchParams.set('page', page);
    window.location = url;
  }

  // --- Accessibility/Feedback ---
  // (Add more snackbar/toast notifications or loading overlays here if desired)

  // Init
  updateSelectionCount();
  console.log('Admin dashboard JS loaded.');
})