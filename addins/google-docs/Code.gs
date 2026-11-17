/**
 * VIDHI AI Checker for Google Docs (Apps Script).
 *
 * Sends the open document's paragraphs to your VIDHI server, shows what the server points out, and highlights or replaces the words you choose.
 * The checks are plain code on the server (no AI). Every finding only points to a place to look; a lawyer decides.
 *
 * Setup (see addins/README.md): in VIDHI make an add-in key (the key works for these two checks only), then open this add-on's Settings and paste the VIDHI address and the key.
 * They are kept in YOUR user properties, not in the document, and are never shown to other people who open it.
 *
 * Google Docs cannot be put into suggestion mode by a script, so "Replace" edits the text directly. Version history (File > Version history) can undo it.
 */

var COLORS = { VERIFIED: '#b7e1cd', PARTLY_VERIFIED: '#fce8b2', NOT_SUPPORTED: '#f4c7c3', code_replacement: '#fce8b2', defect: '#d9d2e9' };
var MAX_CHARS = 300000;

function onOpen() {
  DocumentApp.getUi().createAddonMenu().addItem('Open VIDHI AI Checker', 'showSidebar').addToUi();
}

function onInstall() {
  onOpen();
}

function showSidebar() {
  var html = HtmlService.createHtmlOutputFromFile('Sidebar').setTitle('VIDHI AI Checker');
  DocumentApp.getUi().showSidebar(html);
}

/** The VIDHI address and key of THIS person (user properties). */
function getSettings() {
  var p = PropertiesService.getUserProperties();
  return { url: p.getProperty('VIDHI_URL') || '', hasKey: !!p.getProperty('VIDHI_KEY') };
}

function saveSettings(url, key) {
  url = String(url || '').trim().replace(/\/+$/, '');
  if (!/^https:\/\/[A-Za-z0-9.\-]+(:\d+)?$/.test(url)) {
    throw new Error('The VIDHI address must look like https://your-vidhi-address (https, no path).');
  }
  var p = PropertiesService.getUserProperties();
  p.setProperty('VIDHI_URL', url);
  if (key) {
    key = String(key).trim();
    if (key.indexOf('vk_') !== 0) throw new Error('That does not look like a VIDHI add-in key (it starts with vk_).');
    p.setProperty('VIDHI_KEY', key);
  }
  return getSettings();
}

function clearSettings() {
  PropertiesService.getUserProperties().deleteAllProperties();
  return getSettings();
}

/** Every paragraph and list item in reading order, table cells included. These are the elements the paragraph ids p1, p2, ... refer to. */
function collect_(element, out) {
  var type = element.getType();
  if (type === DocumentApp.ElementType.PARAGRAPH || type === DocumentApp.ElementType.LIST_ITEM) {
    out.push(element);
    return;
  }
  if (typeof element.getNumChildren === 'function') {
    for (var i = 0; i < element.getNumChildren(); i++) collect_(element.getChild(i), out);
  }
}

function paragraphs_() {
  var out = [];
  collect_(DocumentApp.getActiveDocument().getBody(), out);
  return out;
}

/** The server counts characters as Unicode code points; Apps Script counts UTF-16 units. They differ only for characters outside the Basic Multilingual Plane (emoji and the like). */
function unit_(text, cp) {
  return Array.from(text).slice(0, cp).join('').length;
}

function post_(path, payload) {
  var p = PropertiesService.getUserProperties();
  var url = p.getProperty('VIDHI_URL');
  var key = p.getProperty('VIDHI_KEY');
  if (!url || !key) throw new Error('Open Settings and enter the VIDHI address and your add-in key first.');
  var res = UrlFetchApp.fetch(url + path, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + key },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  var code = res.getResponseCode();
  if (code === 401) throw new Error('VIDHI did not accept the key. Make a new key in VIDHI and enter it in Settings.');
  if (code === 403) throw new Error('This VIDHI account may not use the checks. Ask the owner of your organisation.');
  if (code === 429) throw new Error('Too many checks in the last hour. Try again later.');
  if (code !== 200) {
    var detail = '';
    try { detail = JSON.parse(res.getContentText()).detail || ''; } catch (e) { detail = ''; }
    throw new Error('VIDHI answered ' + code + (detail ? ': ' + String(detail).slice(0, 200) : '.'));
  }
  return JSON.parse(res.getContentText());
}

/** Reads the document, asks VIDHI, and returns the findings with the paragraph texts, so a later highlight or replacement can check the document has not changed. */
function scan() {
  var els = paragraphs_();
  var paras = [];
  var total = 0;
  for (var i = 0; i < els.length; i++) {
    var text = els[i].asText().getText();
    total += text.length;
    paras.push({ id: 'p' + (i + 1), text: text });
  }
  if (total > MAX_CHARS) throw new Error('This document is longer than ' + MAX_CHARS + ' characters. Check it in parts.');
  if (!total) throw new Error('There is no text to check.');
  var result = post_('/api/v1/katalyst/analyze-text', { paragraphs: paras });
  result.texts = paras.map(function (p) { return p.text; });
  return result;
}

function target_(index, expectedText) {
  var els = paragraphs_();
  if (index < 0 || index >= els.length) throw new Error('That paragraph is no longer in the document. Scan again.');
  var text = els[index].asText();
  if (text.getText() !== expectedText) throw new Error('The document has changed since the scan. Scan again.');
  return text;
}

/** Colours the words and moves the cursor there. `kind` is a status or a group name (see COLORS). */
function highlight(index, expectedText, startCp, endCp, kind) {
  var text = target_(index, expectedText);
  var s = unit_(expectedText, startCp);
  var e = unit_(expectedText, endCp);
  if (e <= s) {
    // an empty span: put the cursor at the paragraph instead
    DocumentApp.getActiveDocument().setCursor(DocumentApp.getActiveDocument().newPosition(text.getParent(), 0));
    return;
  }
  text.setBackgroundColor(s, e - 1, COLORS[kind] || '#fce8b2');
  var range = DocumentApp.getActiveDocument().newRange().addElement(text, s, e - 1).build();
  DocumentApp.getActiveDocument().setSelection(range);
}

/** Removes the colour from every paragraph (only background colour is cleared). */
function clearHighlights() {
  paragraphs_().forEach(function (el) {
    var t = el.asText();
    var n = t.getText().length;
    if (n) t.setBackgroundColor(0, n - 1, null);
  });
}

/** Replaces the words with a reviewed suggestion. Not a tracked change: Google Docs does not allow that from a script. */
function replace(index, expectedText, startCp, endCp, replacement) {
  var text = target_(index, expectedText);
  var s = unit_(expectedText, startCp);
  var e = unit_(expectedText, endCp);
  if (e <= s || !replacement) throw new Error('There is nothing to replace.');
  text.deleteText(s, e - 1);
  text.insertText(s, String(replacement));
}
