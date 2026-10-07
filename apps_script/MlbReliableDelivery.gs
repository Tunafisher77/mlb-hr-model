/**
 * MLB reliable delivery overlay.
 *
 * Paste this file into the bound MLB Apps Script project alongside the existing
 * mailer. It does not replace the email formatting functions. It makes delivery
 * content-aware: unchanged content sends once; corrected content automatically
 * clears only that report's sent-date marker and resends with the existing sender.
 */

var MLB_RELIABLE_TZ = 'America/Los_Angeles';

function mlbReliableReports_() {
  return [
    {id:'hr', tab:'Email Summary', key:'MLB_HR_EMAIL_SENT_DATE', send:sendDailyMlbHrPicksEmail},
    {id:'game', tab:'Game Email Summary', key:'MLB_GAME_EMAIL_SENT_DATE', send:sendDailyMlbGamePicksEmail},
    {id:'props', tab:'Player Props Email Summary', key:'MLB_PLAYER_PROPS_EMAIL_SENT_DATE', send:sendDailyMlbPlayerPropsEmail},
    {id:'best', tab:'Best Card Email Summary', key:'MLB_BEST_CARD_EMAIL_SENT_DATE', send:sendDailyMlbBestCardEmail}
  ];
}

function runMlbReliableDeliveryChecks() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var props = PropertiesService.getScriptProperties();
    var today = Utilities.formatDate(new Date(), MLB_RELIABLE_TZ, 'yyyy-MM-dd');

    mlbReliableReports_().forEach(function(report) {
      var sheet = ss.getSheetByName(report.tab);
      if (!sheet || sheet.getLastRow() < 1) return;

      var data = sheet.getDataRange().getDisplayValues();
      if (mlbReliableScheduleDate_(data) !== today) return;

      var fingerprint = mlbReliableFingerprint_(data);
      var fingerprintKey = 'MLB_CONTENT_HASH_' + report.id + '_' + today;
      var previous = props.getProperty(fingerprintKey);
      if (previous === fingerprint) return;

      // The existing sender is intentionally date-protected. Clear only this
      // report's marker when its actual published content changed.
      props.deleteProperty(report.key);
      report.send();
      props.setProperty(fingerprintKey, fingerprint);
      console.log((previous ? 'RESENT UPDATED: ' : 'SENT CURRENT: ') + report.id + ' ' + today);
    });
  } finally {
    lock.releaseLock();
  }
}

function mlbReliableScheduleDate_(data) {
  for (var i = 0; i < data.length; i++) {
    if (String(data[i][0] || '').trim() === 'Schedule Date Used') {
      return String(data[i][1] || '').trim().slice(0, 10);
    }
  }
  return '';
}

function mlbReliableFingerprint_(data) {
  var digest = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    JSON.stringify(data),
    Utilities.Charset.UTF_8
  );
  return Utilities.base64EncodeWebSafe(digest);
}

function installMlbReliableDeliveryTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'runMlbReliableDeliveryChecks') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('runMlbReliableDeliveryChecks')
    .timeBased().everyMinutes(5).create();
  console.log('Installed MLB content-aware delivery check every 5 minutes.');
}
