// static/js/admin.js

document.addEventListener('DOMContentLoaded', async () => {
    // --- 1) Load and render stats ---
    try {
      const statsRes = await fetch('/api/admin/stats');
      const stats    = await statsRes.json();
      const statsDiv = document.getElementById('stats');
      const cards    = [
        { label: 'Total',   value: stats.total },
        { label: 'Done',    value: stats.done },
        { label: 'Pending', value: stats.pending },
        { label: 'Error',   value: stats.error }
      ];
      cards.forEach(c => {
        const card = document.createElement('div');
        card.className = 'bg-white dark:bg-gray-800 shadow rounded p-4';
        card.innerHTML = `
          <div class="text-2xl font-bold">${c.value}</div>
          <div class="text-gray-600 dark:text-gray-400">${c.label}</div>
        `;
        statsDiv.appendChild(card);
      });
    } catch (err) {
      console.error('Error loading admin stats:', err);
    }
  
    // --- 2) Load and render articles table ---
    try {
      // Pull up to 1000 items for admin view
      const itemsRes = await fetch('/api/items?page=1&page_size=1000');
      const { items } = await itemsRes.json();
      const tbody     = document.querySelector('#admin-table tbody');
  
      items.forEach(it => {
        const tr = document.createElement('tr');
        tr.className = 'bg-white dark:bg-gray-900 text-sm text-gray-800 dark:text-gray-200';
        tr.innerHTML = `
          <td class="px-4 py-2"><code>${it.id}</code></td>
          <td class="px-4 py-2">${it.title}</td>
          <td class="px-4 py-2">${it.status || 'done'}</td>
          <td class="px-4 py-2">${it.voice || ''}</td>
          <td class="px-4 py-2">${it.publish_date || ''}</td>
          <td class="px-4 py-2">${(it.tags || []).join(', ')}</td>
          <td class="px-4 py-2 text-center space-x-2">
            <button data-id="${it.id}"
                    class="retry-btn px-2 py-1 bg-blue-600 text-white rounded text-xs">
              🔄 Retry
            </button>
            <button data-id="${it.id}"
                    class="edit-btn px-2 py-1 bg-yellow-500 text-white rounded text-xs">
              ✏️ Edit
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
  
      // --- 3) Delegate retry & edit actions ---
      tbody.addEventListener('click', async e => {
        const btn = e.target;
        const id  = btn.dataset.id;
  
        // Retry button
        if (btn.matches('.retry-btn')) {
          btn.disabled = true;
          try {
            const res = await fetch(`/api/items/${id}/retry`, { method: 'POST' });
            if (!res.ok) throw new Error(await res.text());
            btn.textContent = '✅';
          } catch (err) {
            console.error('Retry failed:', err);
            btn.textContent = '⚠️';
          } finally {
            btn.disabled = false;
          }
        }
  
        // Edit button (inline prompt for title)
        if (btn.matches('.edit-btn')) {
          const newTitle = prompt('Enter new title:', btn.closest('tr').querySelector('td:nth-child(2)').textContent);
          if (newTitle !== null) {
            try {
              const res = await fetch(`/api/items/${id}`, {
                method: 'PUT',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ title: newTitle })
              });
              if (!res.ok) throw new Error(await res.text());
              // reload to reflect change
              location.reload();
            } catch (err) {
              console.error('Update failed:', err);
              alert('Failed to update item.');
            }
          }
        }
      });
  
    } catch (err) {
      console.error('Error loading admin items:', err);
    }
  });