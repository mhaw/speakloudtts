// static/js/admin.js
document.addEventListener('DOMContentLoaded', () => {
  const adminTable = document.getElementById('admin-table');
  if (!adminTable) return;

  // --- Toast Notifications ---
  const toastContainer = document.getElementById('toast-container');
  function showToast(message, isError = false) {
    if (!toastContainer) return;
    const toast = document.createElement('div');
    const baseClasses = 'px-4 py-3 rounded-md shadow-lg text-white text-sm transition-all duration-300';
    const a11y = 'role="alert" aria-live="assertive"';
    toast.className = `${baseClasses} ${isError ? 'bg-red-600' : 'bg-green-600'}`;
    toast.innerHTML = `<span ${a11y}>${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(20px)';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

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
    const chks = itemChks();
    if (chks.length > 0) {
      selectAllChk.checked = chks.length === selectedIds().length;
    }
  }

  // --- Action Feedback ---
  function setBulkActionWorking(working) {
    document.getElementById('apply-bulk').disabled = working;
    document.getElementById('bulk-action').disabled = working;
    document.getElementById('retry-stuck')?.toggleAttribute('disabled', working);
  }

  function setRowWorking(row, working) {
    if (!row) return;
    row.classList.toggle('opacity-50', working);
    row.classList.toggle('pointer-events-none', working);
    // Add a spinner or something more visual if you want
  }

  // --- Bulk Actions ---
  document.getElementById('apply-bulk')?.addEventListener('click', async (e) => {
    e.preventDefault();
    const action = document.getElementById('bulk-action').value;
    const ids = selectedIds();
    if (!action || !ids.length) return;
    if (!confirm(`Are you sure you want to ${action} ${ids.length} item(s)?`)) return;
    
    setBulkActionWorking(true);
    try {
      const res = await fetch(`/admin/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ids })
      });
      const resData = await res.json();
      if (!res.ok || !resData.success) {
        throw new Error(resData.error?.message || 'Unknown error occurred.');
      }
      showToast(`Bulk action '${action}' applied successfully.`);
      setTimeout(() => window.location.reload(), 1500);
    } catch (err) {
      showToast(`Bulk action failed: ${err.message}`, true);
    } finally {
      setBulkActionWorking(false);
    }
  });

  // --- Retry All Stuck ---
  document.getElementById('retry-stuck')?.addEventListener('click', async () => {
    if (!confirm("Retry all stuck items?")) return;
    setBulkActionWorking(true);
    try {
      const res = await fetch(`/admin/retry-stuck`, { method: 'POST' });
      const resData = await res.json();
      if (!res.ok || !resData.success) throw new Error(resData.error?.message || 'Unknown error');
      showToast(resData.message || 'Retry enqueued for all stuck items.');
      setTimeout(() => window.location.reload(), 1500);
    } catch (err) {
      showToast(`Retry all failed: ${err.message}`, true);
    } finally {
      setBulkActionWorking(false);
    }
  });

  // --- Per-row actions ---
  async function handleRowAction(e) {
    const button = e.target.closest('.reprocess-btn, .delete-btn, .retry-btn');
    if (!button) return;

    e.preventDefault();
    const id = button.dataset.id;
    const row = button.closest('tr');
    let actionName = 'unknown';
    let endpoint = '';

    if (button.matches('.reprocess-btn')) {
      actionName = 'reprocess';
      endpoint = `/admin/reprocess/${id}`;
    } else if (button.matches('.delete-btn')) {
      actionName = 'delete';
      endpoint = `/admin/delete/${id}`;
    } else if (button.matches('.retry-btn')) {
      actionName = 'retry';
      endpoint = `/admin/retry/${id}`;
    }

    if (!confirm(`Are you sure you want to ${actionName} item ${id}?`)) return;

    setRowWorking(row, true);
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      const resData = await res.json();
      if (!res.ok || !resData.success) throw new Error(resData.error?.message || 'Unknown error');
      showToast(`${actionName.charAt(0).toUpperCase() + actionName.slice(1)} triggered for ${id}.`);
      setTimeout(() => window.location.reload(), 1500);
    } catch (err) {
      showToast(`${actionName} failed: ${err.message}`, true);
      setRowWorking(row, false); // Only turn it off on failure, as page reloads on success
    }
  }
  adminTable.addEventListener('click', handleRowAction);

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

  // Init
  updateSelectionCount();
  console.log('Admin dashboard JS loaded.');
});