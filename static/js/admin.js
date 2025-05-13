// static/js/admin.js

document.addEventListener('DOMContentLoaded', () => {
  const pageSize   = 20;
  let currentPage  = 1;
  let sortKey      = 'publish_date';
  let sortDir      = 'desc';  // 'asc' or 'desc'

  const tbody       = document.querySelector('#admin-table tbody');
  const pageLabel   = document.getElementById('current-page');
  const prevBtn     = document.getElementById('prev-page');
  const nextBtn     = document.getElementById('next-page');
  const headers     = document.querySelectorAll('#admin-table thead th[data-key]');

  // 1) Attach sort handlers
  headers.forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (sortKey === key) {
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        sortKey = key;
        sortDir = 'asc';
      }
      loadPage(currentPage);
    });
  });

  // 2) Pagination handlers
  prevBtn.addEventListener('click', () => {
    if (currentPage > 1) loadPage(--currentPage);
  });
  nextBtn.addEventListener('click', () => loadPage(++currentPage));

  // 3) Fetch & render
  async function loadPage(page) {
    pageLabel.textContent = page;
    tbody.innerHTML = '';
    try {
      const res = await fetch(`/api/items?page=${page}&page_size=${pageSize}`);
      const { items } = await res.json();
      // client-side sort
      items.sort((a,b) => {
        let va = a[sortKey] || '';
        let vb = b[sortKey] || '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return sortDir==='asc'? -1:1;
        if (va > vb) return sortDir==='asc'? 1:-1;
        return 0;
      });

      items.forEach(it => {
        const tr = document.createElement('tr');
        tr.className = 'text-gray-700 dark:text-gray-200';

        function td(txt='') {
          const td = document.createElement('td');
          td.className = 'px-2 py-1 whitespace-nowrap';
          td.textContent = txt;
          return td;
        }

        // status pill
        const pill = document.createElement('span');
        pill.className = {
          done:    'bg-green-100 text-green-800',
          pending: 'bg-yellow-100 text-yellow-800',
          error:   'bg-red-100 text-red-800'
        }[it.status] + ' px-2 py-0.5 rounded-full text-xs';
        pill.textContent = it.status;

        tr.append(
          td(it.id),
          td(it.title),
          (() => { const c = td(); c.append(pill); return c; })(),
          td(it.voice),
          td(it.publish_date.split('T')[0]),
          td(it.reading_time_min + ' min'),
          td(it.submitted_ip),
          td(it.processed_at.split('T')[0] || ''),
          td(it.file_size ? (Math.round(it.file_size/1024)+' KB') : ''),
          (() => {
            const c = document.createElement('td');
            c.className = 'px-2 py-1 whitespace-nowrap space-x-1';
            c.innerHTML = `
              <a href="/items/${it.id}" target="_blank" class="inline-block px-2 py-1 bg-gray-200 dark:bg-gray-700 rounded text-xs">🔗</a>
              <button data-id="${it.id}" class="retry-btn px-2 py-1 bg-blue-600 text-white rounded text-xs">↻</button>
              <button data-id="${it.id}" class="edit-btn px-2 py-1 bg-yellow-500 text-white rounded text-xs">✎</button>
            `;
            return c;
          })()
        );
        tbody.append(tr);
      });

      // disable prev/next if no more data
      prevBtn.disabled = page === 1;
      nextBtn.disabled = tbody.children.length < pageSize;

    } catch (e) {
      console.error('Load page failed', e);
    }
  }

  // 4) Delegate retry & edit (same as before)
  tbody.addEventListener('click', async e => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const id = btn.dataset.id;

    if (btn.matches('.retry-btn')) {
      btn.disabled = true;
      try {
        const r = await fetch(`/api/items/${id}/retry`, { method: 'POST' });
        if (!r.ok) throw await r.text();
        btn.textContent = '✔';
      } catch {
        btn.textContent = '⚠';
      } finally {
        btn.disabled = false;
      }
    }

    if (btn.matches('.edit-btn')) {
      const newTitle = prompt('New title:', btn.closest('tr').children[1].textContent);
      if (newTitle != null) {
        try {
          const r = await fetch(`/api/items/${id}`, {
            method: 'PUT',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ title: newTitle })
          });
          if (!r.ok) throw await r.text();
          loadPage(currentPage);
        } catch {
          alert('Update failed');
        }
      }
    }
  });

  // initial load
  loadPage(1);
});