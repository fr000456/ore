// ==UserScript==
// @name         result
// @match        https://db.netkeiba.com/race/*
// @run-at       document-idle
// @grant        GM.xmlHttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @require      https://code.jquery.com/jquery-3.6.0.min.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/const.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/common.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/html.js
// ==/UserScript==

(function () {
  "use strict";
  const $ = window.jQuery || jQuery;

  (function ($$) {
    function kettou() {
      $$(".race_table_01")
        .find('a[href*="/horse/"]')
        .each(function (index) {
          ajax($$(this).attr("href")).then((html) => {
            kettouFunc(html, $$(this), index, "all");
          });
        });
    }
    function appendMenu() {
      try {
        var kaisekiUl = $$("<ul></ul>", {
          id: "kaisekiUl",
          class: "race_deta_menu",
        });

        // race_deta_menu 内に追加
        $$(".race_deta_menu").append(kaisekiUl);

        // UI構築
        kaisekiUl.append("<br><br>");
        kaisekiUl.append(
          '<li><input placeholder="血統1" type="text" id="kettou1" size="12"></li>',
        );
        kaisekiUl.append(
          '<li><input placeholder="血統2" type="text" id="kettou2" size="12"></li>',
        );
        kaisekiUl.append(
          '<li><input type="button" value="血統" id="kettou"></li>',
        );

        // イベント設定
        $$("#kettou").on("click", () => kettou());

        // 初期値
        $$("#kettou1").val("Danzig");
        $$("#kettou2").val("Nijinsky");

        // 別処理
        sonogo();
      } catch (e) {
        console.log("メニュー生成エラー:", e);
      }
    }
    function init() {
      appendMenu();
    }

    init();
  })($); // ← ★ Tampermonkey jQuery を $$ として安全渡し
})();
