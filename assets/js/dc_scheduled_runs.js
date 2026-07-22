// ------------------------------------------------------
// IBM Cloud PowerVS - Scheduled runs stability
// Reads ../data/dc_scheduled_runs.json and renders table
// Custom sorting like capabilities page (no DataTables)
// ------------------------------------------------------

let allRecords = [];
let currentSort = { column: 'date', direction: 'desc' };
let currentPage = 1;
let rowsPerPage = 10;
let filteredRecords = [];

// Error category colors - loaded dynamically from dc_categories.json
let CATEGORY_COLORS = {};

// Load categories configuration
async function loadCategoriesConfig() {
  try {
    const response = await fetch('../data/dc_categories.json');
    if (!response.ok) {
      console.error('Failed to load dc_categories.json:', response.status);
      return false;
    }
    const config = await response.json();

    // Build CATEGORY_COLORS object from config
    if (config && config.categories) {
      config.categories.forEach(cat => {
        CATEGORY_COLORS[cat.name] = cat.color;
      });
      console.log('Loaded', Object.keys(CATEGORY_COLORS).length, 'category colors from dc_categories.json');
      return true;
    }
    return false;
  } catch (error) {
    console.error('Error loading categories config:', error);
    return false;
  }
}

function updateLastUpdated() {
  const lastUpdatedEl = document.getElementById("last-updated");
  if (!lastUpdatedEl || !allRecords.length) return;

  // Find the most recent record by date
  const mostRecent = allRecords.reduce((latest, record) => {
    const recordDate = record.Date ? record.Date.replace(/<[^>]*>/g, '').trim() : '';
    const latestDate = latest && latest.Date ? latest.Date.replace(/<[^>]*>/g, '').trim() : '';

    if (!latest || recordDate > latestDate) {
      return record;
    }
    return latest;
  }, null);

  if (mostRecent && mostRecent.Date) {
    const dateStr = mostRecent.Date.replace(/<[^>]*>/g, '').trim();
    const date = new Date(dateStr);
    const options = { day: '2-digit', month: 'long', year: 'numeric' };
    const formattedDate = date.toLocaleDateString('en-GB', options);
    lastUpdatedEl.textContent = `Last Updated: ${formattedDate}`;
  }
}

async function loadScheduledRunsData() {
  try {
    // Load categories first
    const categoriesLoaded = await loadCategoriesConfig();
    if (!categoriesLoaded) {
      console.error("Failed to load categories configuration");
      return;
    }

    console.log("Loading dc_scheduled_runs.json...");

    const response = await fetch("../data/dc_scheduled_runs.json", {
      cache: "no-store",
    });

    if (!response.ok) {
      console.error(
        "Failed to load dc_scheduled_runs.json:",
        response.status,
        response.statusText
      );
      return;
    }

    const raw = await response.json();
    allRecords = Array.isArray(raw) ? raw : [];

    if (!allRecords.length) {
      console.warn("dc_scheduled_runs.json is empty or not an array");
      return;
    }

    console.log("Loaded scheduled runs records:", allRecords.length);
    filteredRecords = allRecords;

    // Update last updated timestamp
    updateLastUpdated();

    renderTable();
    setupSorting();
    setupSearch();
    setupPagination();
  } catch (err) {
    console.error("Error fetching dc_scheduled_runs.json:", err);
  }
}

function sortRecords(records, column, direction) {
  return [...records].sort((a, b) => {
    let aVal, bVal;

    // Extract plain text from HTML for date sorting
    if (column === 'date') {
      aVal = a.Date ? a.Date.replace(/<[^>]*>/g, '').toLowerCase() : '';
      bVal = b.Date ? b.Date.replace(/<[^>]*>/g, '').toLowerCase() : '';
    } else if (column === 'workspace') {
      aVal = (a.workspacename || '').toLowerCase();
      bVal = (b.workspacename || '').toLowerCase();
    } else if (column === 'repo') {
      aVal = (a.Repo || '').toLowerCase();
      bVal = (b.Repo || '').toLowerCase();
    } else if (column === 'version') {
      aVal = (a.Version || '').toLowerCase();
      bVal = (b.Version || '').toLowerCase();
    } else {
      aVal = '';
      bVal = '';
    }

    if (direction === 'asc') {
      return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
    } else {
      return aVal < bVal ? 1 : aVal > bVal ? -1 : 0;
    }
  });
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function createTableRow(record) {
  const row = document.createElement('tr');

  // Check if using new multi-error format
  const isMultiError = record.Error && typeof record.Error === 'object' && record.Error.details;

  let errorCellHTML = '';

  if (isMultiError) {
    // New format: multiple errors with structured data
    const errorData = record.Error;
    const errorCount = errorData.errorCount || 0;
    const categories = errorData.categories || [];
    const details = errorData.details || [];

    if (errorCount === 0 || details.length === 0) {
      errorCellHTML = `<div class="error-cell">-</div>`;
    } else {
      // Create summary text
      const summaryText = `${errorCount} Error${errorCount > 1 ? 's' : ''} | ${categories.join(', ')}`;

      // Create detailed error list
      let detailsHTML = '<div class="error-details-list">';
      details.forEach((error, index) => {
        const category = error.category || 'Unknown';
        const categoryColor = CATEGORY_COLORS[category] || '#8d8d8d';

        detailsHTML += `
          <div class="error-detail-item" style="border-left-color: ${categoryColor};">
            <div class="error-detail-number">
              ${index + 1}. <strong>${category}</strong>
            </div>
            <div class="error-detail-field"><strong>Module:</strong> ${error.module || 'N/A'}</div>
            <div class="error-detail-field"><strong>Description:</strong> ${error.description || 'N/A'}</div>
          </div>
        `;
      });
      detailsHTML += '</div>';

      errorCellHTML = `
        <div class="error-cell">
          <div class="errors-main">
            <span class="errors-expand-icon" aria-hidden="true">&#8250;</span>
            <span>${summaryText}</span>
          </div>
          <div class="details-error-text" style="display:none; margin-top:8px;">
            ${detailsHTML}
          </div>
        </div>
      `;
    }
  } else {
    // Legacy format: single error string
    const fullError = record.Errors && String(record.Errors).trim() ? String(record.Errors).trim() : "-";
    let shortError = record.ErrorsShort && String(record.ErrorsShort).trim() ? String(record.ErrorsShort).trim() : fullError;

    const MAX_LEN = 100;
    if (!record.ErrorsShort && shortError.length > MAX_LEN) {
      shortError = shortError.slice(0, MAX_LEN - 3) + "...";
    }

    errorCellHTML = `
      <div class="error-cell">
        <div class="errors-main">
          <span class="errors-expand-icon" aria-hidden="true">&#8250;</span>
          <span>${shortError}</span>
        </div>
        <div class="details-error-text" style="display:none; margin-top:4px;">
          ${fullError}
        </div>
      </div>
    `;
  }

  const workspaceVal = record.workspacename || "-";
  const variationVal = record.Repo || "-";
  const versionVal = record.Version || "-";

  row.innerHTML = `
    <td>${record.Date || "-"}</td>
    <td class="cell-truncate" title="${escapeAttr(workspaceVal)}">${escapeHtml(workspaceVal)}</td>
    <td class="cell-truncate" title="${escapeAttr(variationVal)}">${escapeHtml(variationVal)}</td>
    <td class="cell-truncate" title="${escapeAttr(versionVal)}">${escapeHtml(versionVal)}</td>
    <td>${errorCellHTML}</td>
  `;
  return row;
}

function renderTable(records = allRecords) {
  const tbody = document.getElementById('table-body');
  const rowCountEl = document.getElementById('row-count');
  if (!tbody) return;

  tbody.innerHTML = '';
  filteredRecords = records;

  const sorted = sortRecords(records, currentSort.column, currentSort.direction);

  // Calculate pagination
  const totalPages = Math.ceil(sorted.length / rowsPerPage);
  currentPage = Math.min(currentPage, Math.max(1, totalPages));

  const startIndex = (currentPage - 1) * rowsPerPage;
  const endIndex = startIndex + rowsPerPage;
  const paginatedRecords = sorted.slice(startIndex, endIndex);

  paginatedRecords.forEach(record => {
    const row = createTableRow(record);
    tbody.appendChild(row);
  });

  if (rowCountEl) {
    const start = sorted.length > 0 ? startIndex + 1 : 0;
    const end = Math.min(endIndex, sorted.length);
    rowCountEl.textContent = `${start}-${end} of ${sorted.length} items`;
  }

  updateSortIndicators();
  updatePaginationControls();
}

function updateSortIndicators() {
  document.querySelectorAll('.dc-table th').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
  });

  const currentHeader = document.querySelector(`.dc-table th[data-sort="${currentSort.column}"]`);
  if (currentHeader) {
    currentHeader.classList.add(currentSort.direction === 'asc' ? 'sort-asc' : 'sort-desc');
  }
}

function setupSorting() {
  const headers = document.querySelectorAll('.dc-table th.sortable');

  headers.forEach(header => {
    header.addEventListener('click', function() {
      const column = this.getAttribute('data-sort');

      if (currentSort.column === column) {
        currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
      } else {
        currentSort.column = column;
        currentSort.direction = 'asc';
      }

      currentPage = 1;
      renderTable(filteredRecords);
    });
  });

  updateSortIndicators();
}

function setupSearch() {
  const searchInput = document.getElementById('global-search');
  if (!searchInput) return;

  searchInput.addEventListener('input', function(e) {
    const term = e.target.value.toLowerCase().trim();

    if (!term) {
      currentPage = 1;
      renderTable(allRecords);
      return;
    }

    const filtered = allRecords.filter(record => {
      let searchableText = [
        record.Date || '',
        record.workspacename || '',
        record.Repo || '',
        record.Version || '',
        record.Errors || '',
        record.ErrorsShort || ''
      ];

      // Add new error structure fields to search
      if (record.Error && typeof record.Error === 'object') {
        if (record.Error.categories) {
          searchableText.push(record.Error.categories.join(' '));
        }
        if (record.Error.details) {
          record.Error.details.forEach(detail => {
            searchableText.push(detail.category || '');
            searchableText.push(detail.module || '');
            searchableText.push(detail.description || '');
          });
        }
      }

      return searchableText.join(' ').toLowerCase().includes(term);
    });

    currentPage = 1;
    renderTable(filtered);
  });
}

// Toggle expand/collapse for error details
document.addEventListener('click', function(e) {
  const errorsMain = e.target.closest('.errors-main');
  if (!errorsMain) return;

  const container = errorsMain.closest('.error-cell');
  if (!container) return;

  const fullDiv = container.querySelector('.details-error-text');
  const icon = container.querySelector('.errors-expand-icon');
  if (!fullDiv || !icon) return;

  const isHidden = fullDiv.style.display === 'none' || fullDiv.style.display === '';
  if (isHidden) {
    fullDiv.style.display = 'block';
    icon.classList.add('rotated');
  } else {
    fullDiv.style.display = 'none';
    icon.classList.remove('rotated');
  }
});

function setupPagination() {
  const pageSizeSelect = document.getElementById('page-size');
  const prevButton = document.getElementById('prev-page');
  const nextButton = document.getElementById('next-page');

  if (pageSizeSelect) {
    pageSizeSelect.addEventListener('change', function(e) {
      rowsPerPage = parseInt(e.target.value);
      currentPage = 1;
      renderTable(filteredRecords);
    });
  }

  if (prevButton) {
    prevButton.addEventListener('click', function() {
      if (currentPage > 1) {
        currentPage--;
        renderTable(filteredRecords);
      }
    });
  }

  if (nextButton) {
    nextButton.addEventListener('click', function() {
      const totalPages = Math.ceil(filteredRecords.length / rowsPerPage);
      if (currentPage < totalPages) {
        currentPage++;
        renderTable(filteredRecords);
      }
    });
  }
}

function updatePaginationControls() {
  const totalPages = Math.ceil(filteredRecords.length / rowsPerPage) || 1;
  const prevButton = document.getElementById('prev-page');
  const nextButton = document.getElementById('next-page');

  if (prevButton) {
    prevButton.disabled = currentPage <= 1;
  }

  if (nextButton) {
    nextButton.disabled = currentPage >= totalPages;
  }
}

function formatDateLink(dateHtml) {
  if (!dateHtml || typeof dateHtml !== 'string') {
    return "-";
  }

  const wrapper = document.createElement('div');
  wrapper.innerHTML = dateHtml.trim();

  const anchor = wrapper.querySelector('a');
  if (!anchor) {
    return dateHtml;
  }

  anchor.setAttribute('target', '_blank');
  anchor.setAttribute('rel', 'noopener noreferrer');

  return anchor.outerHTML;
}

document.addEventListener("DOMContentLoaded", function () {
  loadScheduledRunsData();
});

// Made with Bob
