// ------------------------------------------------------
// IBM Cloud PowerVS - Scheduled runs error analytics
// Reads ../data/dc_scheduled_runs.json and renders charts
// ------------------------------------------------------

let allRecords = [];
let filteredRecords = [];
let errorChart = null;

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

// ------------------------------------------------------
// Theme and style helpers
// ------------------------------------------------------

function isDarkModeActive() {
  return window.matchMedia &&
    window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function ensureErrorAnalyticsStyles() {
  if (document.getElementById('error-analytics-theme-styles')) return;

  const style = document.createElement('style');
  style.id = 'error-analytics-theme-styles';

  style.textContent = `
    :root {
      --ea-bg: #ffffff;
      --ea-surface: #ffffff;
      --ea-surface-hover: #e8e8e8;
      --ea-border: #e0e0e0;
      --ea-text: #161616;
      --ea-muted-text: #525252;
      --ea-link: #0f62fe;
      --ea-highlight: #e8f4ff;
      --ea-selected-badge: #d0e2ff;
      --ea-selected-border: #0f62fe;
      --ea-table-header: #f4f4f4;
      --ea-overlay: rgba(22, 22, 22, 0.55);
    }

    @media (prefers-color-scheme: dark) {
      :root {
        --ea-bg: #161616;
        --ea-surface: #262626;
        --ea-surface-hover: #333333;
        --ea-border: #525252;
        --ea-text: #f4f4f4;
        --ea-muted-text: #c6c6c6;
        --ea-link: #78a9ff;
        --ea-highlight: #1e3a5f;
        --ea-selected-badge: #0f62fe;
        --ea-selected-border: #78a9ff;
        --ea-table-header: #393939;
        --ea-overlay: rgba(0, 0, 0, 0.65);
      }
    }

    #errorDetailsModal {
      background-color: var(--ea-overlay);
    }

    #errorDetailsContent {
      background: var(--ea-bg);
      color: var(--ea-text);
    }

    .ea-zone-panel {
      margin-bottom: 1.5rem;
      padding: 1rem 1.5rem;
      background: var(--ea-surface);
      border: 1px solid var(--ea-border);
      color: var(--ea-text);
    }

    .ea-zone-title {
      margin: 0 0 0.75rem 0;
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--ea-text);
    }

    .ea-zone-list {
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      align-items: center;
    }

    .zone-filter-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 0.75rem;
      background: var(--ea-surface);
      border: 1px solid var(--ea-border);
      color: var(--ea-text);
      cursor: pointer;
      transition: background-color 0.2s, border-color 0.2s, color 0.2s;
      user-select: none;
    }

    .zone-filter-badge:hover {
      background: var(--ea-surface-hover);
    }

    .zone-filter-badge.is-selected {
      background: var(--ea-selected-badge);
      border-color: var(--ea-selected-border);
    }

    .zone-filter-badge-count {
      font-size: 0.875rem;
      font-weight: 600;
      color: var(--ea-link);
    }

    .zone-filter-badge.is-selected .zone-filter-badge-count {
      color: var(--ea-text);
    }

    .dc-table {
      width: 100%;
      border-collapse: collapse;
      font-family: 'IBM Plex Sans', Arial, sans-serif;
      background: var(--ea-bg);
      color: var(--ea-text);
    }

    .dc-table thead tr {
      background: var(--ea-table-header);
    }

    .dc-table th {
      padding: 1rem;
      text-align: left;
      font-weight: 600;
      font-size: 0.875rem;
      color: var(--ea-text);
      border-bottom: 1px solid var(--ea-border);
    }

    .dc-table td {
      padding: 1rem;
      font-size: 0.875rem;
      color: var(--ea-text);
      border-bottom: 1px solid var(--ea-border);
      background: var(--ea-surface);
      vertical-align: top;
    }

    .dc-table tr.error-row.is-highlighted td {
      background: var(--ea-highlight);
    }

    .dc-table tr.error-row.is-dimmed td {
      opacity: 0.45;
    }

    .dc-table a {
      color: var(--ea-link);
      text-decoration: none;
    }

    .dc-table a:hover {
      text-decoration: underline;
    }

    .ea-mono {
      font-family: 'IBM Plex Mono', monospace;
      word-break: break-word;
      max-width: 800px;
      font-size: 0.8125rem;
    }
  `;

  document.head.appendChild(style);
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

function applyChartTheme() {
  if (!errorChart) return;

  const isDark = isDarkModeActive();

  const textColor = isDark ? '#f4f4f4' : '#161616';
  const gridColor = isDark ? '#404040' : '#e0e0e0';

  if (errorChart.options.scales?.y?.ticks) {
    errorChart.options.scales.y.ticks.color = textColor;
  }

  if (errorChart.options.scales?.x?.ticks) {
    errorChart.options.scales.x.ticks.color = textColor;
  }

  if (errorChart.options.scales?.y?.grid) {
    errorChart.options.scales.y.grid.color = gridColor;
  }

  if (errorChart.options.plugins?.datalabels) {
    errorChart.options.plugins.datalabels.color = textColor;
  }

  errorChart.update();
}

// ------------------------------------------------------
// Helper function to extract categories from a record
// ------------------------------------------------------

function extractCategories(record) {
  const categories = [];

  // New format: Error object with categories array
  if (record.Error && typeof record.Error === 'object') {
    if (record.Error.categories && Array.isArray(record.Error.categories)) {
      categories.push(...record.Error.categories);
    } else if (record.Error.details && Array.isArray(record.Error.details)) {
      // Extract from details if categories array is missing
      record.Error.details.forEach(detail => {
        if (detail.category) {
          categories.push(detail.category);
        }
      });
    }
  }

  // Legacy format: ErrorsShort field
  if (categories.length === 0 && record.ErrorsShort) {
    categories.push(record.ErrorsShort);
  }

  // Legacy format: Errors field
  if (categories.length === 0 && record.Errors) {
    categories.push('Unknown'); // Default to Unknown for old unstructured errors
  }

  return categories.length > 0 ? categories : ['Unknown'];
}

// ------------------------------------------------------
// Load data from JSON
// ------------------------------------------------------

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

    // Initialize filters
    populateFilters();

    // Apply initial filter (all data)
    applyFilters();

  } catch (err) {
    console.error("Error fetching dc_scheduled_runs.json:", err);
  }
}

// ------------------------------------------------------
// Populate filter dropdowns
// ------------------------------------------------------

function populateFilters() {
  // Get unique values for each filter
  const zones = [...new Set(allRecords.map(r => r.DC).filter(Boolean))].sort();
  const images = [...new Set(allRecords.map(r => r.OS).filter(Boolean))].sort();
  const variations = [...new Set(allRecords.map(r => r.Repo).filter(Boolean))].sort();

  // Populate zone filter
  const zoneSelect = document.getElementById('filter-zone');
  if (zoneSelect) {
    zoneSelect.innerHTML = '<option value="">All zones</option>';
    zones.forEach(zone => {
      const option = document.createElement('option');
      option.value = zone;
      option.textContent = zone;
      zoneSelect.appendChild(option);
    });
  }

  // Populate image filter
  const imageSelect = document.getElementById('filter-image');
  if (imageSelect) {
    imageSelect.innerHTML = '<option value="">All images</option>';
    images.forEach(image => {
      const option = document.createElement('option');
      option.value = image;
      option.textContent = image;
      imageSelect.appendChild(option);
    });
  }

  // Populate variation filter
  const variationSelect = document.getElementById('filter-variation');
  if (variationSelect) {
    variationSelect.innerHTML = '<option value="">All variations</option>';
    variations.forEach(variation => {
      const option = document.createElement('option');
      option.value = variation;
      option.textContent = variation;
      variationSelect.appendChild(option);
    });
  }

  // Set default date range (last 30 days)
  const today = new Date();
  const thirtyDaysAgo = new Date(today);
  thirtyDaysAgo.setDate(today.getDate() - 30);

  const dateTo = document.getElementById('filter-date-to');
  const dateFrom = document.getElementById('filter-date-from');

  if (dateTo) {
    dateTo.valueAsDate = today;
  }

  if (dateFrom) {
    dateFrom.valueAsDate = thirtyDaysAgo;
  }
}

// ------------------------------------------------------
// Extract date from HTML link
// ------------------------------------------------------

function extractDate(dateHtml) {
  if (!dateHtml) return null;
  const match = String(dateHtml).match(/(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
}

// ------------------------------------------------------
// Apply filters
// ------------------------------------------------------

function applyFilters() {
  const dateFrom = document.getElementById('filter-date-from')?.value || '';
  const dateTo = document.getElementById('filter-date-to')?.value || '';
  const zone = document.getElementById('filter-zone')?.value || '';
  const image = document.getElementById('filter-image')?.value || '';
  const variation = document.getElementById('filter-variation')?.value || '';

  filteredRecords = allRecords.filter(record => {
    // Date filter
    if (dateFrom || dateTo) {
      const recordDate = extractDate(record.Date);
      if (!recordDate) return false;

      if (dateFrom && recordDate < dateFrom) return false;
      if (dateTo && recordDate > dateTo) return false;
    }

    // Zone filter
    if (zone && record.DC !== zone) return false;

    // Image filter
    if (image && record.OS !== image) return false;

    // Variation filter
    if (variation && record.Repo !== variation) return false;

    return true;
  });

  console.log(`Filtered records: ${filteredRecords.length} of ${allRecords.length}`);

  // Update visualizations
  updateStatistics();
  updateChart();
}

// ------------------------------------------------------
// Reset filters
// ------------------------------------------------------

function resetFilters() {
  const dateFrom = document.getElementById('filter-date-from');
  const dateTo = document.getElementById('filter-date-to');
  const zone = document.getElementById('filter-zone');
  const image = document.getElementById('filter-image');
  const variation = document.getElementById('filter-variation');

  if (dateFrom) dateFrom.value = '';
  if (dateTo) dateTo.value = '';
  if (zone) zone.value = '';
  if (image) image.value = '';
  if (variation) variation.value = '';

  applyFilters();
}

// ------------------------------------------------------
// Update statistics cards
// ------------------------------------------------------

function updateStatistics() {
  const totalErrors = filteredRecords.length;

  // Count unique categories (each record can have multiple categories)
  const categories = {};
  filteredRecords.forEach(record => {
    const recordCategories = extractCategories(record);
    recordCategories.forEach(category => {
      categories[category] = (categories[category] || 0) + 1;
    });
  });

  const uniqueCategories = Object.keys(categories).length;

  // Find most common error
  let mostCommon = '-';
  let maxCount = 0;
  for (const [category, count] of Object.entries(categories)) {
    if (count > maxCount) {
      maxCount = count;
      mostCommon = category;
    }
  }

  // Get date range
  let dateRange = '-';
  if (filteredRecords.length > 0) {
    const dates = filteredRecords
      .map(r => extractDate(r.Date))
      .filter(Boolean)
      .sort();

    if (dates.length > 0) {
      const minDate = dates[0];
      const maxDate = dates[dates.length - 1];
      dateRange = minDate === maxDate ? minDate : `${minDate} to ${maxDate}`;
    }
  }

  // Update DOM
  const totalErrorsEl = document.getElementById('total-errors');
  const uniqueCategoriesEl = document.getElementById('unique-categories');
  const dateRangeEl = document.getElementById('date-range');
  const mostCommonEl = document.getElementById('most-common');

  if (totalErrorsEl) totalErrorsEl.textContent = totalErrors;
  if (uniqueCategoriesEl) uniqueCategoriesEl.textContent = uniqueCategories;
  if (dateRangeEl) dateRangeEl.textContent = dateRange;
  if (mostCommonEl) mostCommonEl.textContent = mostCommon;
}

// ------------------------------------------------------
// Update chart
// ------------------------------------------------------

function updateChart() {
  // Count errors by category (each record can have multiple categories)
  const categoryCounts = {};
  filteredRecords.forEach(record => {
    const recordCategories = extractCategories(record);
    recordCategories.forEach(category => {
      categoryCounts[category] = (categoryCounts[category] || 0) + 1;
    });
  });

  // Sort by count (descending)
  const sortedCategories = Object.entries(categoryCounts)
    .sort((a, b) => b[1] - a[1]);

  const labels = sortedCategories.map(([category]) => category);
  const data = sortedCategories.map(([, count]) => count);
  const colors = labels.map(label => CATEGORY_COLORS[label] || '#8d8d8d');

  // Destroy existing chart if it exists
  if (errorChart) {
    errorChart.destroy();
  }

  const chartEl = document.getElementById('errorChart');
  if (!chartEl) {
    console.warn("Chart canvas with id 'errorChart' not found");
    return;
  }

  // Create new chart
  const ctx = chartEl.getContext('2d');

  errorChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Number of Occurrences',
        data: data,
        backgroundColor: colors,
        borderColor: colors,
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      onClick: (event, elements) => {
        if (elements.length > 0) {
          const index = elements[0].index;
          const category = labels[index];
          showErrorDetails(category);
        }
      },
      plugins: {
        legend: {
          display: false
        },
        title: {
          display: false
        },
        tooltip: {
          backgroundColor: 'rgba(22, 22, 22, 0.9)',
          titleColor: '#ffffff',
          bodyColor: '#ffffff',
          borderColor: '#525252',
          borderWidth: 1,
          padding: 12,
          displayColors: true,
          callbacks: {
            label: function(context) {
              const total = data.reduce((a, b) => a + b, 0);
              const percentage = total > 0
                ? ((context.parsed.y / total) * 100).toFixed(1)
                : '0.0';
              return `${context.parsed.y} occurrences (${percentage}%)`;
            }
          }
        },
        datalabels: {
          anchor: 'end',
          align: 'top',
          color: '#161616',
          font: {
            family: "'IBM Plex Sans', Arial, sans-serif",
            size: 14,
            weight: 'bold'
          },
          formatter: (value) => value
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            stepSize: 1,
            color: '#161616',
            font: {
              family: "'IBM Plex Sans', Arial, sans-serif",
              size: 12
            }
          },
          grid: {
            color: '#e0e0e0'
          }
        },
        x: {
          ticks: {
            color: '#161616',
            font: {
              family: "'IBM Plex Sans', Arial, sans-serif",
              size: 12
            },
            maxRotation: 45,
            minRotation: 45
          },
          grid: {
            display: false
          }
        }
      }
    }
  });

  applyChartTheme();
}

// ------------------------------------------------------
// Extract URL from Date HTML
// ------------------------------------------------------

function extractUrl(dateHtml) {
  if (!dateHtml) return null;
  const match = String(dateHtml).match(/href="([^"]+)"/);
  return match ? match[1] : null;
}

// ------------------------------------------------------
// Show error details modal
// ------------------------------------------------------

function showErrorDetails(category) {
  ensureErrorAnalyticsStyles();

  const modal = document.getElementById('errorDetailsModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalContent = document.getElementById('errorDetailsContent');

  if (!modal || !modalTitle || !modalContent) {
    console.warn('Error details modal elements not found');
    return;
  }

  modalContent.style.background = 'var(--ea-bg)';
  modalContent.style.color = 'var(--ea-text)';

  // Adjust modal position based on side nav state
  adjustModalForSideNav();

  // Filter records by category
  const categoryRecords = filteredRecords.filter(record => {
    const categories = extractCategories(record);
    return categories.includes(category);
  });

  // Count occurrences by zone
  const zoneCounts = {};
  categoryRecords.forEach(record => {
    const zone = record.DC || 'N/A';
    zoneCounts[zone] = (zoneCounts[zone] || 0) + 1;
  });

  // Sort zones by count (descending)
  const sortedZones = Object.entries(zoneCounts).sort((a, b) => b[1] - a[1]);

  // Build zone counter section
  let zoneCounterHTML = `
    <div class="ea-zone-panel">
      <h3 class="ea-zone-title">Zone Distribution</h3>
      <div class="ea-zone-list">
  `;

  sortedZones.forEach(([zone, count]) => {
    zoneCounterHTML += `
      <div class="zone-filter-badge" data-zone="${escapeAttr(zone)}">
        <span>${escapeHtml(zone)}</span>
        <span class="zone-filter-badge-count">${count}</span>
      </div>
    `;
  });

  zoneCounterHTML += `
      </div>
    </div>
  `;

  // Build table HTML with Carbon Design styling matching dc_scheduled_runs.html
  let tableHTML = `
    <table class="dc-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Zone</th>
          <th>Image</th>
          <th>Variation</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
  `;

  categoryRecords.forEach(record => {
    const jobUrl = extractUrl(record.Date);
    const date = extractDate(record.Date) || 'N/A';
    const zone = record.DC || 'N/A';
    const image = record.OS || 'N/A';
    const variation = record.Repo || 'N/A';

    // Extract error details for this category
    let description = 'N/A';

    if (record.Error && record.Error.details && Array.isArray(record.Error.details)) {
      const errorDetail = record.Error.details.find(d => d.category === category);
      if (errorDetail) {
        description = errorDetail.description || 'N/A';
      }
    }

    // Create job link cell
    const jobCell = jobUrl
      ? `<a href="${escapeAttr(jobUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(date)}</a>`
      : escapeHtml(date);

    tableHTML += `
      <tr class="error-row" data-zone="${escapeAttr(zone)}">
        <td>${jobCell}</td>
        <td>${escapeHtml(zone)}</td>
        <td>${escapeHtml(image)}</td>
        <td>${escapeHtml(variation)}</td>
        <td>${escapeHtml(description)}</td>
      </tr>
    `;
  });

  tableHTML += `
      </tbody>
    </table>
  `;

  modalTitle.textContent = `${category} - ${categoryRecords.length} Occurrence${categoryRecords.length !== 1 ? 's' : ''}`;
  modalContent.innerHTML = zoneCounterHTML + tableHTML;
  modal.style.display = 'block';

  // Add click handlers for zone badges
  const zoneBadges = modalContent.querySelectorAll('.zone-filter-badge');
  let selectedZone = null;

  zoneBadges.forEach(badge => {
    badge.addEventListener('click', function() {
      const clickedZone = this.getAttribute('data-zone');
      const errorRows = modalContent.querySelectorAll('.error-row');

      // Toggle selection
      if (selectedZone === clickedZone) {
        selectedZone = null;

        zoneBadges.forEach(b => {
          b.classList.remove('is-selected');
        });

        errorRows.forEach(row => {
          row.style.display = '';
          row.classList.remove('is-highlighted');
        });

        return;
      }

      selectedZone = clickedZone;

      // Update badge styles
      zoneBadges.forEach(b => {
        b.classList.toggle(
          'is-selected',
          b.getAttribute('data-zone') === clickedZone
        );
      });

      // Show only matching rows, hide non-matching rows
      errorRows.forEach(row => {
        const isMatch = row.getAttribute('data-zone') === clickedZone;
        if (isMatch) {
          row.style.display = '';
          row.classList.add('is-highlighted');
        } else {
          row.style.display = 'none';
        }
      });
    });
  });
}

// ------------------------------------------------------
// Adjust modal for side navigation state
// ------------------------------------------------------

function adjustModalForSideNav() {
  const sideNav = document.querySelector('[data-side-nav]');
  const modalContent = document.querySelector('.modal-content');
  const header = document.querySelector('.bx--header');

  if (!sideNav || !modalContent) return;

  const isExpanded = sideNav.classList.contains('bx--side-nav--expanded');
  const isRail = sideNav.classList.contains('bx--side-nav--rail');

  // Get header height and add small spacing
  const headerHeight = header ? header.offsetHeight : 48; // Default to 48px if header not found
  const topMargin = `calc(${headerHeight}px + 1rem)`;

  if (isExpanded) {
    // Side nav is expanded (16rem = 256px)
    // Position modal with spacing after the menu
    modalContent.style.marginTop = topMargin;
    modalContent.style.marginLeft = 'calc(16rem + 2rem)';
    modalContent.style.marginRight = '2rem';
    modalContent.style.width = 'calc(100% - 16rem - 4rem)';
    modalContent.style.maxWidth = 'none';
  } else if (isRail) {
    // Side nav is in rail mode (3rem = 48px)
    // Position modal with spacing after the collapsed menu
    modalContent.style.marginTop = topMargin;
    modalContent.style.marginLeft = 'calc(3rem + 2rem)';
    modalContent.style.marginRight = '2rem';
    modalContent.style.width = 'calc(100% - 3rem - 4rem)';
    modalContent.style.maxWidth = 'none';
  } else {
    // Side nav is hidden - center the modal normally
    modalContent.style.marginTop = '3%';
    modalContent.style.marginLeft = 'auto';
    modalContent.style.marginRight = 'auto';
    modalContent.style.width = '95%';
    modalContent.style.maxWidth = '1900px';
  }
}

// ------------------------------------------------------
// Close modal
// ------------------------------------------------------

function closeErrorDetailsModal() {
  const modal = document.getElementById('errorDetailsModal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// ------------------------------------------------------
// Toggle filters dropdown
// ------------------------------------------------------

function toggleFilters() {
  const filtersContent = document.getElementById('filters-content');
  const filtersChevron = document.querySelector('.filters-chevron');

  if (filtersContent) {
    filtersContent.classList.toggle('expanded');
  }

  if (filtersChevron) {
    filtersChevron.classList.toggle('expanded');
  }
}

// ------------------------------------------------------
// Event listeners
// ------------------------------------------------------

document.addEventListener("DOMContentLoaded", function () {
  ensureErrorAnalyticsStyles();
  loadScheduledRunsData();

  // Filters toggle
  const filtersToggle = document.getElementById('filters-toggle');
  if (filtersToggle) {
    filtersToggle.addEventListener('click', toggleFilters);
  }

  // Apply filters button
  const applyFiltersButton = document.getElementById('apply-filters');
  if (applyFiltersButton) {
    applyFiltersButton.addEventListener('click', applyFilters);
  }

  // Reset filters button
  const resetFiltersButton = document.getElementById('reset-filters');
  if (resetFiltersButton) {
    resetFiltersButton.addEventListener('click', resetFilters);
  }

  // Modal close button
  const closeModalButton = document.getElementById('closeModal');
  if (closeModalButton) {
    closeModalButton.addEventListener('click', closeErrorDetailsModal);
  }

  // Close modal when clicking outside
  const errorDetailsModal = document.getElementById('errorDetailsModal');
  if (errorDetailsModal) {
    errorDetailsModal.addEventListener('click', function(e) {
      if (e.target === this) {
        closeErrorDetailsModal();
      }
    });
  }

  // Listen for dark mode changes
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      applyChartTheme();
    });
  }

  // Listen for side nav toggle to adjust modal
  const sideNavToggle = document.querySelector('.bx--side-nav__toggle');
  if (sideNavToggle) {
    sideNavToggle.addEventListener('click', function() {
      // Wait for the toggle animation to complete
      setTimeout(adjustModalForSideNav, 50);
    });
  }

  // Also observe side nav class changes using MutationObserver
  const sideNav = document.querySelector('[data-side-nav]');
  if (sideNav) {
    const observer = new MutationObserver(function(mutations) {
      mutations.forEach(function(mutation) {
        if (mutation.attributeName === 'class') {
          adjustModalForSideNav();
        }
      });
    });
    observer.observe(sideNav, { attributes: true });
  }
});
