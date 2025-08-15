// Dashboard JS extracted from template and lightly refactored

(function () {
  const logDiv = document.getElementById('log');
  const botToggle = document.getElementById('botToggle');
  const botStatusText = document.getElementById('bot-status-text');
  const botToggleLabel = document.getElementById('bot-toggle-label');

  let lastActivityId = 0;
  let pendingBotToggle = false;
  let originalBotState = false;
  let currentService = null;

  function addLogEntry(message, className = 'text-primary') {
    if (!logDiv) return;
    const timestamp = new Date().toLocaleTimeString();
    const logEntry = document.createElement('div');
    logEntry.className = 'log-entry ' + className;
    logEntry.innerHTML = `
      <i class="fas fa-circle me-2" style="font-size: 6px;"></i>
      <small class="text-muted">${timestamp}</small> ${message}
    `;
    logDiv.insertBefore(logEntry, logDiv.firstChild);
    while (logDiv.children.length > 20) logDiv.removeChild(logDiv.lastChild);
  }

  function getActivityIcon(type) {
    const icons = {
      scraper_status: '📥',
      new_analysis: '🧠',
      manual_trade_success: '✅',
      trade_error: '❌',
      trade_rejected: '🚫',
      trade_skipped: '⏸️',
      scraper_error: '⚠️',
      analysis_error: '⚠️',
      trade_status_updated: '🔄'
    };
    return icons[type] || 'ℹ️';
  }

  function getActivityClass(type) {
    const classes = {
      scraper_status: 'text-primary',
      new_analysis: 'text-info',
      manual_trade_success: 'text-success',
      trade_error: 'text-danger',
      trade_rejected: 'text-danger',
      trade_skipped: 'text-warning',
      scraper_error: 'text-danger',
      analysis_error: 'text-danger',
      trade_status_updated: 'text-info'
    };
    return classes[type] || 'text-muted';
  }

  function pollForUpdates() {
    fetch('/api/recent-activities/')
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.activities.length > 0) {
          const newActivities = data.activities.filter((a) => a.id > lastActivityId);
          newActivities.reverse().forEach((activity) => {
            const icon = getActivityIcon(activity.type);
            const timestamp = new Date(activity.created_at).toLocaleTimeString();
            addLogEntry(`${icon} ${activity.message}`, getActivityClass(activity.type), timestamp);
            lastActivityId = Math.max(lastActivityId, activity.id);
          });
        }
      })
      .catch((e) => console.error('Error polling for updates:', e));
  }

  function updateAPIStatus(apiStatus) {
    const statusMap = {
      openai: { index: 0 },
      news_sources: { index: 1 },
      alpaca: { index: 2 }
    };
    const badges = document.querySelectorAll('#api-status-row .status-badge');
    Object.keys(statusMap).forEach((api) => {
      const statusInfo = apiStatus[api];
      const badge = badges[statusMap[api].index];
      if (badge && statusInfo) {
        const statusText = statusInfo.status;
        const isOk = statusText === 'ok';
        badge.className = 'badge status-badge ' + (isOk ? 'bg-success' : statusText === 'warning' ? 'bg-warning text-dark' : 'bg-danger');
        badge.textContent = isOk ? 'Connected' : statusText === 'warning' ? 'Warning' : 'Error';
        const cardContainer = badge.closest('.col-md-4');
        const card = cardContainer ? cardContainer.querySelector('.card') : null;
        if (card) {
          card.classList.remove('connected', 'disconnected', 'loading');
          if (isOk) card.classList.add('connected'); else card.classList.add('disconnected');
        }
        if (api === 'news_sources') {
          const detailsElement = document.getElementById('news-sources-details');
          if (detailsElement && statusInfo.count !== undefined) {
            detailsElement.textContent = `${statusInfo.active_count}/${statusInfo.count} active`;
          }
        }
      }
    });
  }

  function refreshActivitiesFromDatabase() {
    fetch('/api/recent-activities/')
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.activities && data.activities.length > 0 && logDiv) {
          while (logDiv.children.length > 1) logDiv.removeChild(logDiv.lastChild);
          data.activities.slice(0, 20).forEach((activity) => {
            const node = document.createElement('div');
            node.className = 'log-entry text-secondary';
            node.innerHTML = `
              <i class="fas fa-database me-2" style="font-size: 6px;"></i>
              <small class="text-muted">${activity.created_at}</small> ${activity.message}
            `;
            logDiv.appendChild(node);
          });
          if (logDiv.children.length > 1) addLogEntry('📁 Showing recent activities from database', 'text-info');
        }
      })
      .catch(() => {});
  }

  function refreshData() {
    fetch('/api/system-status/')
      .then((r) => r.json())
      .then((data) => {
        updateAPIStatus(data.api_status);
        const byId = (id) => document.getElementById(id);
        byId('posts-count').textContent = data.statistics.posts_24h || 0;
        byId('analyses-count').textContent = data.statistics.analyses_24h || 0;
        byId('trades-count').textContent = data.statistics.trades_24h || 0;
        byId('win-rate').textContent = (data.performance.win_rate || 0) + '%';
        byId('sources-active').textContent = data.statistics.active_sources || 0;
        
        // Display actual scraping times
        if (data.scraping_times && data.scraping_times.last_scrape) {
          const lastScrapeTime = new Date(data.scraping_times.last_scrape);
          byId('last-scrape').textContent = lastScrapeTime.toLocaleTimeString();
        } else {
          byId('last-scrape').textContent = 'Never';
        }
        
        if (data.scraping_times && data.scraping_times.next_scrape) {
          const nextScrapeTime = new Date(data.scraping_times.next_scrape);
          const now = new Date();
          
          // Show time if it's in the future, otherwise show "Due now"
          if (nextScrapeTime > now) {
            byId('next-scrape').textContent = nextScrapeTime.toLocaleTimeString();
          } else {
            byId('next-scrape').textContent = 'Due now';
          }
        } else {
          byId('next-scrape').textContent = 'Not scheduled';
        }
        byId('pending-analysis').textContent = (data.statistics.total_posts - data.statistics.total_analyses) || 0;
        byId('avg-confidence').textContent = (data.performance.avg_confidence || 0) + '%';
        byId('last-analysis').textContent = 'Recently';
        byId('open-positions').textContent = data.statistics.open_trades || 0;
        const totalPnlVal = Number(data.performance.total_pnl_24h || data.performance.total_pnl || 0);
        const dayPnlVal = Number(data.performance.day_pnl || 0);
        byId('total-pnl').textContent = '$' + totalPnlVal.toFixed(2);
        byId('day-pnl').textContent = '$' + dayPnlVal.toFixed(2);
        byId('account-value').textContent = '$' + (data.performance.account_value || 10000).toLocaleString();
        if (data.trading_config && data.trading_config.bot_enabled !== undefined) {
          const botEnabled = data.trading_config.bot_enabled;
          if (botToggle) botToggle.checked = botEnabled;
          originalBotState = botEnabled;
          if (botStatusText) botStatusText.textContent = botEnabled ? 'Bot is currently active and monitoring markets' : 'Bot is currently disabled';
          if (botToggleLabel) botToggleLabel.textContent = botEnabled ? 'ENABLED' : 'DISABLED';
        }
      })
      .catch((e) => {
        console.error('Error fetching system status:', e);
        addLogEntry('Failed to refresh system data', 'text-danger');
      });
    refreshActivitiesFromDatabase();
  }

  function showBotToggleConfirmation(newState) {
    const isEnabling = newState;
    const iconElement = document.getElementById('botToggleConfirmIcon');
    const alertElement = document.getElementById('botToggleConfirmAlert');
    const titleElement = document.getElementById('botToggleConfirmTitle');
    const messageElement = document.getElementById('botToggleConfirmMessage');
    const buttonElement = document.getElementById('botToggleConfirmButton');
    const buttonTextElement = document.getElementById('botToggleConfirmButtonText');
    if (isEnabling) {
      iconElement.className = 'fas fa-play-circle text-success';
      alertElement.className = 'alert alert-success';
      titleElement.textContent = 'Enable Trading Bot?';
      messageElement.textContent = 'This will activate all bot activities including automated scraping, analysis, and trading based on your configuration.';
      buttonElement.className = 'btn btn-success';
      buttonTextElement.textContent = 'Enable Bot';
    } else {
      iconElement.className = 'fas fa-stop-circle text-danger';
      alertElement.className = 'alert alert-danger';
      titleElement.textContent = 'Disable Trading Bot?';
      messageElement.textContent = 'This will stop all bot activities including scraping, analysis, and trading. Existing open positions will remain active but no new trades will be executed.';
      buttonElement.className = 'btn btn-danger';
      buttonTextElement.textContent = 'Disable Bot';
    }
    pendingBotToggle = newState;
    const modal = new bootstrap.Modal(document.getElementById('botToggleConfirmModal'));
    modal.show();
  }

  function confirmBotToggle() {
    const modalEl = document.getElementById('botToggleConfirmModal');
    const modal = bootstrap.Modal.getInstance(modalEl);
    if (modal) {
      modal.hide();
      // Defensive cleanup for lingering backdrops
      setTimeout(() => {
        if (typeof modal.dispose === 'function') {
          try { modal.dispose(); } catch (e) { /* noop */ }
        }
        document.querySelectorAll('.modal-backdrop.show').forEach((el) => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('padding-right');
      }, 200);
    }
    updateBotStatus();
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + '=') {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function updateBotStatus() {
    fetch('/api/toggle-bot-status/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') }
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          const statusText = data.bot_enabled ? 'enabled' : 'disabled';
          addLogEntry(`Bot ${statusText} successfully`, 'text-success');
          if (botToggle) botToggle.checked = data.bot_enabled;
          if (botStatusText) botStatusText.textContent = data.bot_enabled ? 'Bot is currently active and monitoring markets' : 'Bot is currently disabled';
          if (botToggleLabel) botToggleLabel.textContent = data.bot_enabled ? 'ENABLED' : 'DISABLED';
          originalBotState = data.bot_enabled;
        } else {
          addLogEntry(`Failed to update bot status: ${data.error}`, 'text-danger');
          if (botToggle) botToggle.checked = originalBotState;
        }
      })
      .catch(() => {
        addLogEntry('Failed to update bot status', 'text-danger');
        if (botToggle) botToggle.checked = originalBotState;
      });
  }

  function checkConnection(service) {
    currentService = service;
    const modal = new bootstrap.Modal(document.getElementById('connectionCheckModal'));
    document.getElementById('connectionCheckResult').innerHTML = `
      <div class="text-center">
        <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Checking connection...</span></div>
        <p class="mt-2">Checking ${service.toUpperCase()} connection...</p>
      </div>`;
    document.getElementById('connectionCheckModalLabel').innerHTML = `
      <i class="fas fa-link me-2"></i>${service.toUpperCase()} Connection Check`;
    modal.show();
    fetch(`/api/check-connection/${service}`)
      .then((r) => r.json())
      .then((data) => displayConnectionResult(data, service))
      .catch((error) => displayConnectionResult({ status: 'error', message: 'Failed to check connection: ' + error.message }, service));
  }

  function recheckConnection() { if (currentService) checkConnection(currentService); }

  function displayConnectionResult(data, service) {
    const resultDiv = document.getElementById('connectionCheckResult');
    let statusIcon, statusClass, statusText;
    switch (data.status) {
      case 'ok':
        statusIcon = 'fas fa-check-circle'; statusClass = 'text-success'; statusText = 'Connected'; break;
      case 'warning':
        statusIcon = 'fas fa-exclamation-triangle'; statusClass = 'text-warning'; statusText = 'Warning'; break;
      case 'error':
        statusIcon = 'fas fa-times-circle'; statusClass = 'text-danger'; statusText = 'Error'; break;
      default:
        statusIcon = 'fas fa-question-circle'; statusClass = 'text-secondary'; statusText = 'Unknown';
    }
    let html = `
      <div class="text-center mb-3">
        <i class="${statusIcon} ${statusClass}" style="font-size: 3rem;"></i>
        <h4 class="mt-2 ${statusClass}">${statusText}</h4>
      </div>
      <div class="alert alert-${data.status === 'ok' ? 'success' : data.status === 'warning' ? 'warning' : 'danger'}">
        <strong>Status:</strong> ${data.message}
      </div>`;
    if (data.account_status) {
      html += `
        <div class="row">
          <div class="col-6"><strong>Account Status:</strong><br><span class="badge bg-info">${data.account_status}</span></div>`;
      if (data.buying_power) {
        html += `<div class="col-6"><strong>Buying Power:</strong><br><span class="text-success">$${data.buying_power}</span></div>`;
      }
      html += `</div>`;
    }
    if (data.count !== undefined) {
      html += `<div class="mt-2"><strong>Sources:</strong> ${data.active_count}/${data.count} active</div>`;
    }
    resultDiv.innerHTML = html;
  }

  function init() {
    addLogEntry('🚀 Dashboard initialized with live polling', 'text-success');
    pollForUpdates();
    setInterval(pollForUpdates, 3000);
    refreshData();
    setInterval(refreshData, 30000);
    if (botToggle) {
      botToggle.addEventListener('change', function (e) {
        e.preventDefault();
        const newState = this.checked;
        this.checked = originalBotState;
        showBotToggleConfirmation(newState);
      });
    }
    const botToggleModal = document.getElementById('botToggleConfirmModal');
    if (botToggleModal) {
      botToggleModal.addEventListener('hidden.bs.modal', function () {
        if (botToggle) botToggle.checked = originalBotState;
        // Extra cleanup to avoid stuck dark overlay
        document.querySelectorAll('.modal-backdrop.show').forEach((el) => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('padding-right');
      });
    }
    addLogEntry('Dashboard fully loaded and ready', 'text-success');
    // Expose a few helpers for inline handlers
    window.checkConnection = checkConnection;
    window.recheckConnection = recheckConnection;
    window.confirmBotToggle = confirmBotToggle;
    // Navbar quick tools
    window.exportSystemData = function () {
      if (confirm('Export system data to CSV? This may take a moment.')) {
        alert('Data export functionality coming soon!');
      }
    };
    window.viewSystemLogs = function () {
      window.open('/admin/core/', '_blank');
    };
    window.clearSystemCache = function () {
      if (confirm('Clear system cache? This will refresh all cached data.')) {
        alert('Cache clearing functionality coming soon!');
      }
    };
  }

  document.addEventListener('DOMContentLoaded', init);
})();


