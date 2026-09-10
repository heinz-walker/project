/**
 * 임직원 정보보안 교육 웹앱 - Google Apps Script 백엔드 (익명화 버전)
 *
 * 원래 백엔드 구조를 보여주기 위한 참고용 코드이며, 그대로 실행되지는 않는다.
 * - SPREADSHEET_ID 등 식별자는 플레이스홀더로 대체했다.
 * - 모의 피싱 로그인 페이지 서빙 로직은 특정 쇼핑몰(base href) 의존성을 제거하고
 *   일반화된 목업 서빙으로 주석 처리했다. 공개 데모(index.html)에서는 이 함수 대신
 *   클라이언트가 iframe.srcdoc으로 목업을 직접 렌더링한다.
 */

function doGet(e) {
  var page = (e && e.parameter && e.parameter.page) || 'index';
  return HtmlService.createHtmlOutputFromFile(page)
    .setTitle('임직원 정보보안 교육')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * 모의 피싱 실습용 로그인 목업 HTML을 반환한다.
 * (원래는 특정 쇼핑몰 로그인 페이지를 복제하고 <base href>로 자원 경로를 맞췄으나,
 *  공개용에서는 브랜드 의존성을 제거하고 일반화된 목업만 서빙한다.)
 */
function getMockShopHtml() {
  var html = HtmlService.createHtmlOutputFromFile('mockshop').getContent();
  // 원본에서는 아래처럼 외부 도메인 base href를 주입했으나 공개용에서는 제거했다.
  // if (html.indexOf('<base ') === -1) {
  //   html = html.replace('<head>', '<head><base href="<YOUR_SHOP_BASE_URL>">');
  // }
  return html;
}

/**
 * 이수 정보(소속·성명·별점·피드백)를 스프레드시트에 적재한다.
 */
function saveToSheet(data) {
  var SPREADSHEET_ID = '<YOUR_SPREADSHEET_ID>';
  var SHEET_NAME = 'response';

  try {
    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = ss.getSheetByName(SHEET_NAME);

    if (!sheet) {
      sheet = ss.insertSheet(SHEET_NAME);
      sheet.appendRow(['타임스탬프', '소속', '성명', '별점', '피드백']);
    }

    var timestamp = new Date();
    sheet.appendRow([timestamp, data.dept, data.name, data.rating || '', data.feedback || '']);

    return { success: true };
  } catch (e) {
    throw new Error(e.toString());
  }
}
