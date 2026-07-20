// ==UserScript==
// @name         result
// @match        https://db.netkeiba.com/race/*
// @run-at       document-idle
// @grant        GM.xmlHttpRequest
// @connect      localhost
// @connect      127.0.0.1
// @require      https://code.jquery.com/jquery-3.6.0.min.js
// @require      https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js
// @require      https://gist.githubusercontent.com/fr000456/d9c0f4a161df409d303683b51410b619/raw/1e7b38b633ac5700d99ded1254570ad7069e93b6/const
// @require      https://gist.githubusercontent.com/fr000456/cc4230bcd2f1da38e70d65fffb46c73a/raw/c972fa7c3eeff4ffec5cee4ddbd7c2aa8a0346a1/common
// @require      https://gist.githubusercontent.com/fr000456/84bbff4bc370aba05010f53380597adb/raw/c9c60d6a820571616b4bfcfbd74849ce5fc895f1/html
// ==/UserScript==

(function () {
    "use strict";
    const $ = window.jQuery || jQuery;

    (function ($$) {
        function kettou() {
            $$('.race_table_01').find('a[href*="/horse/"]').each(function (index) {
                ajax($$(this).attr('href')).then((html) => {
                    kettouFunc(html, $$(this), index, 'all');
                });
            });
        }
        function appendMenu() {
            try {
                var kaisekiUl = $$("<ul></ul>", {
                    id: "kaisekiUl",
                    class: "race_deta_menu"
                });

                // race_deta_menu 内に追加
                $$('.race_deta_menu').append(kaisekiUl);

                // UI構築
                kaisekiUl.append('<br><br>');
                kaisekiUl.append('<li><input placeholder="血統1" type="text" id="kettou1" size="12"></li>');
                kaisekiUl.append('<li><input placeholder="血統2" type="text" id="kettou2" size="12"></li>');
                kaisekiUl.append('<li><input type="button" value="血統" id="kettou"></li>');

                // イベント設定
                $$('#kettou').on('click', () => kettou());

                // 初期値
                $$('#kettou1').val("Danzig");
                $$('#kettou2').val("Nijinsky");

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

    })($);  // ← ★ Tampermonkey jQuery を $$ として安全渡し
})();
