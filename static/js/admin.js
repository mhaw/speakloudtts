// static/js/admin.js

document.addEventListener('DOMContentLoaded', () => {
  // Guard: Only run if #admin-table exists
  const adminTable = document.getElementById('admin-table');
  if (!adminTable) return;

  const pageSize     = 20;
  let currentPage    = 1;
  let sortKey        = 'publish_date';
  let sortDir        = 'desc';

  const tbody        = adminTable.querySelector('tbody');
  const pageLabel    = document.getElementById('current-page');
  const totalCountEl = document.getElementById('total-count');
  const prevBtn      = document.getElementById('prev-page');
  const nextBtn      = document.getElementById('next-page');
  const headers      = adminTable.querySelectorAll('thead th[data-key]');
  const searchInput  = document.getElementById('admin-search');
  const exportBtn    = document.getElementById('export-csv-btn');
  const bulkRetryBtn = document.getElementById('bulk-retry-btn');
  const selectAllChk = document.getElementById('select-all');

  // Sorting
  headers.forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (sortKey === key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      else { sortKey = key; sortDir = 'asc'; }
      loadPage(currentPage);
    });
  });

  // Pagination
  if (prevBtn) prevBtn.addEventListener('click', () => {
    if (currentPage > 1) loadPage(currentPage - 1);
  });
  if (nextBtn) nextBtn.addEventListener('click', () => loadPage(currentPage + 1));

  // Search filter
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.trim().toLowerCase();
      tbody.querySelectorAll('tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  }

  // Export CSV
  if (exportBtn) {
    exportBtn.addEventListener('click', () => {
      window.location.href = '/api/admin/items.csv';
    });
  }

  // Select all checkbox
  if (selectAllChk) {
    selectAllChk.addEventListener('change', () => {
      const checked = selectAllChk.checked;
      tbody.querySelectorAll('input.row-select').forEach(cb => cb.checked = checked);
    });
  }

  // Bulk retry
  if (bulkRetryBtn) {
    bulkRetryBtn.addEventListener('click', async () => {
      const ids = Array.from(tbody.querySelectorAll('input.row-select:checked'))
                       .map(cb => cb.value);
      if (!ids.length) return alert('Select at least one row');
      bulkRetryBtn.disabled = true;
      try {
        const res = await fetch('/api/admin/bulk-retry', {
          method: 'POST',
          headers: { 'Content-Type':'application/json' },
          body: JSON.stringify({ ids })
        });
        if (!res.ok) throw new Error(await res.text());
        alert('Retry enqueued for ' + ids.length + ' items');
        loadPage(currentPage);
      } catch (e) {
        alert('Bulk retry failed: ' + e);
      } finally {
        bulkRetryBtn.disabled = false;
      }
    });
  }

  // Load & render a page
  async function loadPage(page) {
    currentPage = page;
    if (pageLabel) pageLabel.textContent = page;
    tbody.innerHTML = '';
    try {
      const res = await fetch(`/api/admin/items?page=${page}&page_size=${pageSize}`);
      const { items, total_count } = await res.json();
      if (totalCountEl) totalCountEl.textContent = `${total_count} total articles`;

      // Client-side sort for safety
      items.sort((a, b) => {
        let va = a[sortKey] || '', vb = b[sortKey] || '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        return va < vb ? (sortDir === 'asc' ? -1 : 1)
                       : va > vb ? (sortDir === 'asc' ? 1 : -1) : 0;
      });

      items.forEach(it => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="px-2 py-1 break-all">${it.id}</td>
          <td class="px-2 py-1">${it.title || 'Untitled'}</td>
          <td class="px-2 py-1">${it.status || ''}</td>
          <td class="px-2 py-1">${it.voice || ''}</td>
          <td class="px-2 py-1">${it.publish_date ? it.publish_date.split('T')[0] : ''}</td>
          <td class="px-2 py-1">${it.word_count || '—'}</td>
          <td class="px-2 py-1">${it.submitted_ip || '—'}</td>
          <td class="px-2 py-1">${it.submitted_at_fmt || '—'}</td>
          <td class="px-2 py-1">${it.storage_bytes ? Math.round(it.storage_bytes / 1024) + ' KB' : ''}</td>
          <td class="px-2 py-1">
            <a href="/item/${it.id}" target="_blank" class="text-blue-600 hover:underline">View</a>
          </td>`;
        tbody.appendChild(tr);
      });

      if (prevBtn) prevBtn.disabled = page === 1;
      if (nextBtn) nextBtn.disabled = (page * pageSize) >= total_count;

      // Show a message if there are no items
      if (items.length === 0) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="10" class="px-4 py-4 text-center text-gray-500">No articles found.</td>`;
        tbody.appendChild(tr);
      }
    } catch (e) {
      console.error('Load page failed', e);
      if (tbody) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="10" class="px-4 py-4 text-center text-red-500">Error loading items.</td>`;
        tbody.appendChild(tr);
      }
    }
  }

  // Initial load
  loadPage(1);
});