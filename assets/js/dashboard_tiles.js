/**
 * Dashboard Tiles Component
 * Handles Error Analysis and Recent Runs tiles
 */

// Color palette for error categories - loaded dynamically from dc_categories.json
let ERROR_COLORS = {};

// Load categories configuration
async function loadCategoriesConfig() {
  try {
    const response = await fetch('../data/dc_categories.json');
    if (!response.ok) {
      console.error('Failed to load dc_categories.json:', response.status);
      return false;
    }
    const config = await response.json();

    // Build ERROR_COLORS object from config
    if (config && config.categories) {
      config.categories.forEach(cat => {
        ERROR_COLORS[cat.name] = cat.color;
      });
      console.log('Loaded', Object.keys(ERROR_COLORS).length, 'category colors from dc_categories.json');
      return true;
    }
    return false;
  } catch (error) {
    console.error('Error loading categories config:', error);
    return false;
  }
}

/**
 * Extract date from run data
 */
function extractDate(dateString) {
    const match = dateString.match(/>([\d-]+)</);
    return match ? match[1] : null;
}

/**
 * Get current month in YYYY-MM format
 */
function getCurrentMonth() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    return `${year}-${month}`;
}

/**
 * Analyze errors from scheduled runs data - last 30 days
 */
function analyzeErrors(data) {
    const errorStats = {};
    let totalErrors = 0;
    const now = new Date();
    const thirtyDaysAgo = new Date(now.getTime() - (30 * 24 * 60 * 60 * 1000));

    data.forEach(run => {
        if (run.Error && run.Error.categories) {
            const dateStr = extractDate(run.Date);
            if (!dateStr) return;

            const runDate = new Date(dateStr);

            if (runDate >= thirtyDaysAgo && runDate <= now) {
                totalErrors += run.Error.errorCount || 0;

                run.Error.categories.forEach(category => {
                    if (!errorStats[category]) {
                        errorStats[category] = 0;
                    }
                    const categoryCount = run.Error.details.filter(
                        detail => detail.category === category
                    ).length;
                    errorStats[category] += categoryCount;
                });
            }
        }
    });

    return { errorStats, totalErrors };
}

/**
 * Draw donut chart using Canvas API
 */
function drawDonutChart(canvasId, data, colors) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const radius = Math.min(centerX, centerY) - 10;
    const innerRadius = radius * 0.6;

    const total = Object.values(data).reduce((sum, val) => sum + val, 0);
    const gapAngle = 0.01;
    if (total === 0) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    let currentAngle = -Math.PI / 2;

    Object.entries(data).forEach(([category, count]) => {
        const sliceAngle = (count / total) * 2 * Math.PI;


        const startAngle = currentAngle + gapAngle / 2;
        const endAngle = currentAngle + sliceAngle - gapAngle / 2;


        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, startAngle, endAngle);
        ctx.arc(centerX, centerY, innerRadius, endAngle, startAngle, true);
        ctx.closePath();


        ctx.fillStyle = colors[category] || '#8d8d8d';
        ctx.fill();

        currentAngle += sliceAngle;
    });

    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';

    ctx.beginPath();
    ctx.arc(centerX, centerY, innerRadius, 0, 2 * Math.PI);
    ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('background-color') || '#ffffff';
    ctx.fill();

    ctx.lineWidth = 1;              // Stärke des Randes
    ctx.strokeStyle = '#000000';    // schwarze Trennlinie
    ctx.stroke();
}

/**
 * Create legend HTML
 */
function createLegend(data, colors) {
    const sortedData = Object.entries(data).sort((a, b) => b[1] - a[1]);

    return sortedData.map(([category, count]) => `
        <div class="legend-item">
            <div class="legend-color" style="background-color: ${colors[category] || '#8d8d8d'}"></div>
            <div class="legend-text">
                <span class="legend-category">${category}</span>
                <span class="legend-count">${count}</span>
            </div>
        </div>
    `).join('');
}

/**
 * Get recent errors (last 5)
 */
function getRecentErrors(data) {
    // Sort by date descending (newest first) as a safety measure
    const sortedData = [...data].sort((a, b) => {
        const dateA = extractDate(a.Date) || '';
        const dateB = extractDate(b.Date) || '';
        return dateB.localeCompare(dateA);
    });

    return sortedData.slice(0, 5).map(run => ({
        dc: run.workspacename,
        date: extractDate(run.Date) || 'N/A',
        errorCount: run.Error?.errorCount || 0,
        topCategory: run.Error?.categories?.[0] || 'Unknown'
    }));
}

/**
 * Create recent errors HTML
 */
function createRecentErrorsHTML(recentErrors) {
    return recentErrors.map(error => `
        <div class="recent-error-item">
            <div class="error-item-header">
                <span class="error-item-dc">${error.dc}</span>
                <span class="error-item-date">${error.date}</span>
            </div>
            <div class="error-item-category">${error.errorCount} Errors - ${error.topCategory}</div>
        </div>
    `).join('');
}

/**
 * Initialize dashboard tiles
 */
async function initDashboardTiles() {
    // Load categories first
    const categoriesLoaded = await loadCategoriesConfig();
    if (!categoriesLoaded) {
        console.error("Failed to load categories configuration");
        return;
    }

    // Load scheduled runs data (errors and recent runs)
    try {
        // Fetch scheduled runs data
        const runsResponse = await fetch('../data/dc_scheduled_runs.json');
        const runsData = await runsResponse.json();

        // Analyze errors (last 30 days)
        const { errorStats, totalErrors } = analyzeErrors(runsData);

        // Update total errors count
        const totalElement = document.getElementById('total-errors');
        if (totalElement) {
            totalElement.textContent = totalErrors;
        }

        // Update total runs count (all runs)
        const totalRunsElement = document.getElementById('total-runs');
        if (totalRunsElement) {
            totalRunsElement.textContent = runsData.length;
        }

        // Draw chart
        drawDonutChart('error-chart', errorStats, ERROR_COLORS);

        // Create legend
        const legendElement = document.getElementById('error-legend');
        if (legendElement) {
            legendElement.innerHTML = createLegend(errorStats, ERROR_COLORS);
        }

        // Create recent errors list
        const recentErrorsElement = document.getElementById('recent-errors-list');
        if (recentErrorsElement) {
            const recentErrors = getRecentErrors(runsData);
            recentErrorsElement.innerHTML = createRecentErrorsHTML(recentErrors);
        }

        // Add resize handler to redraw chart
        window.addEventListener('resize', () => {
            drawDonutChart('error-chart', errorStats, ERROR_COLORS);
        });

    } catch (error) {
        console.error('Error loading scheduled runs data:', error);
        const totalElement = document.getElementById('total-errors');
        if (totalElement) {
            totalElement.textContent = '-';
        }
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDashboardTiles);
} else {
    initDashboardTiles();
}
