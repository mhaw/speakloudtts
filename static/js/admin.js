// static/js/admin.js

document.addEventListener('DOMContentLoaded', () => {
  const pageSize     = 20;
  let currentPage    = 1;
  let sortKey        = 'publish_date';
  let sortDir        = 'desc';
  const tbody        = document.querySelector('#admin-table tbody');
  const pageLabel    = document.getElementById('current-page');
  const prevBtn      = document.getElementById('prev-page');
  const nextBtn      = document.getElementById('next-page');
  const headers      = document.querySelectorAll('#admin-table thead th[data-key]');
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
  prevBtn.addEventListener('click', () => {
    if (currentPage > 1) loadPage(--currentPage);
  });
  nextBtn.addEventListener('click', () => loadPage(++currentPage));

  // Search filter
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    tbody.querySelectorAll('tr').forEach(row => {
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });

  // Export CSV
  exportBtn.addEventListener('click', () => {
    window.location.href = '/api/admin/items.csv';
  });

  // Select all checkbox
  selectAllChk.addEventListener('change', () => {
    const checked = selectAllChk.checked;
    tbody.querySelectorAll('input.row-select').forEach(cb => cb.checked = checked);
  });

  // Bulk retry
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

  // Load & render a page
  async function loadPage(page) {
    currentPage = page;
    pageLabel.textContent = page;
    tbody.innerHTML = '';
    try {
      const res = await fetch(`/api/admin/items?page=${page}&page_size=${pageSize}`);
      const { items } = await res.json();
      // client-side sort
      items.sort((a,b) => {
        let va = a[sortKey]||'', vb = b[sortKey]||'';
        if (typeof va==='string') va = va.toLowerCase();
        if (typeof vb==='string') vb = vb.toLowerCase();
        return va < vb ? (sortDir==='asc'?-1:1)
                        : va > vb ? (sortDir==='asc'?1:-1) : 0;
      });

      items.forEach(it => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="px-2 py-1 whitespace-nowrap">
            <input type="checkbox" class="row-select" value="${it.id}">
          </td>
          <td class="px-2 py-1 whitespace-nowrap">${it.id}</td>
          <td class="px-2 py-1">${it.title}</td>
          <td class="px-2 py-1 whitespace-nowrap">${it.status}</td>
          <td class="px-2 py-1 whitespace-nowrap">${it.voice}</td>
          <td class="px-2 py-1 whitespace-nowrap">${it.publish_date.split('T')[0]}</td>
          <td class="px-2 py-1 whitespace-nowrap">${it.reading_time_min} min</td>
          <td class="px-2 py-1 whitespace-nowrap">${it.submitted_ip}</td>
          <td class="px-2 py-1 whitespace-nowrap">${(it.processed_at||'').split('T')[0]}</td>
          <td class="px-2 py-1 whitespace-nowrap">
            ${it.storage_bytes ? Math.round(it.storage_bytes/1024) + ' KB' : ''}
          </td>
          <td class="px-2 py-1 whitespace-nowrap space-x-1">
            <a href="/items/${it.id}" target="_blank" class="px-2 py-1 bg-gray-200 dark:bg-gray-700 rounded text-xs">🔗</a>
            <button data-id="${it.id}" class="retry-btn px-2 py-1 bg-blue-600 text-white rounded text-xs">↻</button>
            <button data-id="${it.id}" class="edit-btn px-2 py-1 bg-yellow-500 text-white rounded text-xs">✎</button>
          </td>`;
        tbody.appendChild(tr);
      });

      prevBtn.disabled = page === 1;
      nextBtn.disabled = tbody.children.length < pageSize;
    } catch (e) {
      console.error('Load page failed', e);
    }
  }

  // Delegate retry & inline edit
  tbody.addEventListener('click', async e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.classList.contains('retry-btn')) {
      btn.disabled = true;
      try {
        const r = await fetch(`/api/items/${id}/retry`, { method:'POST' });
        if (!r.ok) throw new Error(await r.text());
        btn.textContent = '✔';
      } catch {
        btn.textContent = '⚠';
      } finally {
        btn.disabled = false;
      }
    }
    if (btn.classList.contains('edit-btn')) {
      const newTitle = prompt('New title:', btn.closest('tr').children[2].textContent);
      if (newTitle!=null) {
        try {
          const r = await fetch(`/api/items/${id}`, {
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ title:newTitle })
          });
          if (!r.ok) throw new Error(await r.text());
          loadPage(currentPage);
        } catch {
          alert('Update failed');
        }
      }
    }
  });

  // Initial load
  loadPage(1);
});