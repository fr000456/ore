// ==UserScript==
// @name keikou
// @namespace    http://tampermonkey.net/
// @version      0.1
// @include https://db.netkeiba.com/?pid=race_list*
// @run-at       document-idle
// @grant        none
// @require https://code.jquery.com/jquery-3.6.0.min.js
// @require https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js
// @require https://cdnjs.cloudflare.com/ajax/libs/jquery.tablesorter/2.31.3/js/jquery.tablesorter.min.js
// @require https://gist.githubusercontent.com/fr000456/cc4230bcd2f1da38e70d65fffb46c73a/raw/c972fa7c3eeff4ffec5cee4ddbd7c2aa8a0346a1/common?v=2
// @require https://gist.githubusercontent.com/fr000456/d9c0f4a161df409d303683b51410b619/raw/1e7b38b633ac5700d99ded1254570ad7069e93b6/const
// @require https://gist.githubusercontent.com/fr000456/84bbff4bc370aba05010f53380597adb/raw/c9c60d6a820571616b4bfcfbd74849ce5fc895f1/html
// ==/UserScript==

(function ($) {

    function init() {
        //ボタン、テーブル追加
        addHtml();
        //イベント追加
        bindFunc();
    }

    function addHtml() {
        var keikouUl = $("<ul></ul>", { id: "keikouUl", class: "search_result_box" });
        $('.search_result_box').append(keikouUl);
        //血統ボタン
        keikouUl.append('<li><input type="button" value="血統" id="kettou"></li>');
        //枠順ボタン
        keikouUl.append('<li><input type="button" value="枠順" id="wakujun"></li>');
        //前走レースボタン
        keikouUl.append('<li><input type="button" value="前走レース" id="zensou"></li>');
        //前走距離ボタン
        keikouUl.append('<li><input type="button" value="前走距離" id="kyori"></li>');

        var resultTbl = $("<table></table>", { id: "resultTbl", class: "nk_tb_common race_table_01" });

        // 横並び用のコンテナ div を作成
        const $group = $('<div class="checkbox-group" style="display: flex; gap: 15px; margin: 10px 0;"></div>');

        // チェックボックスの項目を配列で定義
        const items = [
            { label: '１着', value: '1' },
            { label: '２着', value: '2' },
            { label: '３着', value: '3' },
            { label: '着外', value: '4' },
        ];

        // 各チェックボックスを作成して追加
        items.forEach(item => {
            const $checkbox = $(`
      <label style="display: flex; align-items: center; gap: 5px;">
        <input type="checkbox" name="options" value="${item.value}">
        ${item.label}
      </label>
    `);
            $group.append($checkbox);
        });
        keikouUl.append($group);
        keikouUl.append(resultTbl);
    };

    function bindFunc() {
        $('#kettou').bind('click', function () { kaiseki(kettouTyakujunSum) });
        $('#wakujun').bind('click', function () { kaiseki(wakujunFunc, 'cancel') });
        $('#zensou').bind('click', function () { kaiseki(zensouTyakujunSum) });
        $('#kyori').bind('click', function () { kaiseki(kyoriTyakujunSum) });
    }

    async function kaiseki(func, cancel) {
        $('#resultTbl tbody').empty();
        const promises = [];

        // レースリンクを取得
        const raceLinks = $('.race_table_01 a').get();

        for (const el of raceLinks) {
            const raceUrl = $(el).attr('href');

            if (raceUrl.indexOf("/race/") == -1 ||
                raceUrl.indexOf("/sum/") != -1 ||
                raceUrl.indexOf("/movie/") != -1 ||
                raceUrl.indexOf("/list/") != -1) {
                continue;
            }

            // レース解析をPromise化してpush
            const p = (async () => {
                const raceResulthtml = await ajax(raceUrl);

                if (cancel) {
                    func(raceResulthtml);
                    return;
                }

                // 馬リンクを取得して並列処理
                const horseLinks = $(raceResulthtml).find('#raceResult a[href*="/horse/"]').toArray();
                const horsePromises = horseLinks.map(async (el, index) => {
                    const href = el.getAttribute('href');
                    const match = href.match(/horse\/([A-Za-z0-9\-]+)/);
                    if (!match) {
                        console.warn('馬IDが取れませんでした:', href);
                        return;
                    }
                    const horseId = match[1].trim();
                    const html = await getHtmlFromMap(horseId);
                    setIndex(html, index);
                    return func(html, raceUrl, index);
                });

                await Promise.all(horsePromises);
                console.log('全馬解析完了:', raceUrl);
            })();

            promises.push(p); // ← ここで外側の配列に追加
        }

        // 全レースの解析完了を待つ
        await Promise.all(promises);

        // テーブル描画
        $('#resultTbl').trigger("destroy").tablesorter();
        console.log('解析終わり');

        // サイズ確認
        estimateIndexedDBSize("MyCacheDB", "cache").then(size => {
            console.log("IndexedDB size (bytes):", size);
        });
    }

    const zensouTyakujunSum = function (html, raceNo, index) {
        const raceTd = $('<div>').html(html).find('#data').find('tbody').find('tr').find('td').find('a[href*="' + raceNo + '"]').parent().parent().next();

        if (raceTd) {
            const race = raceTd.find('td').eq(4).text();
            const tyakujun = raceTd.find('td').eq(11).text();
            let shouldFetch = false;
            $('input[name="options"]:checked').each(function () {
                const val = $(this).val();
                if (val === '4') {
                    if (tyakujun > 3) {
                        shouldFetch = true;
                        return false;
                    }
                } else if (val === tyakujun) {
                    shouldFetch = true;
                    return false;
                }
            });
            if (shouldFetch) {
                makeResultTbl(race.slice(0, race.indexOf('(')), index);
            }
        }
    };

    const kyoriTyakujunSum = function (html, raceNo, index) {
        const raceTd = $('<div>').html(html).find('#data').find('tbody').find('tr').find('td').find('a[href*="' + raceNo + '"]').parent().parent().next();
        if (raceTd) {
            const kyori = raceTd.find('td').eq(14).text();
            const tyakujun = raceTd.find('td').eq(11).text();
            let shouldFetch = false;
            $('input[name="options"]:checked').each(function () {
                const val = $(this).val();
                if (val === '4') {
                    if (tyakujun > 3) {
                        shouldFetch = true;
                        return false;
                    }
                } else if (val === tyakujun) {
                    shouldFetch = true;
                    return false;
                }
            });
            if (shouldFetch) {
                makeResultTbl(kyori, index);
            }
        }
    };

    const kettouTyakujunSum = function (html, a, index) {
        const sire = $('<div>').html(html).find('#kettou').find('.blood_table').find('a').first().attr('title');
        makeResultTbl(sire, index);
    };

    const wakujunFunc = function (raceHtml) {
        $(raceHtml).find('.race_table_01').find('tr').each(function (index) {
            if (index == 0) {
                return true;
            }
            makeResultTbl($(this).find('td').eq(2).text(), index - 1);
        });
    };

    function makeResultTbl(key, value) {
        if (!key) { return; }

        //ヘッダー
        if ($("#resultTbl").find('tr').length == 0) {
            var tblHd = $("<thead></thead>");
            var tblTr = $("<tr></tr>");
            tblHd.append(tblTr);
            tblTr.append($('<th></th>'));
            tblTr.append($('<th></th>').text('1着'));
            tblTr.append($('<th></th>').text('2着'));
            tblTr.append($('<th></th>').text('3着'));
            tblTr.append($('<th></th>').text('着外'));
            tblTr.append($('<th></th>').text('勝率'));
            tblTr.append($('<th></th>').text('連対率'));
            tblTr.append($('<th></th>').text('複勝率'));
            $("#resultTbl").append(tblHd);
        }

        // tbodyがなければ追加
        if ($("#resultTbl tbody").length === 0) {
            $("#resultTbl").append('<tbody></tbody>');
        }

        var tr = $("<tr></tr>");
        if (!$("#resultTbl").find('#' + key).length) {
            tr = tr.attr('id', key);
            $("#resultTbl tbody").append(tr);
            var tdKey = $("<td></td>");
            tdKey.text(key);
            var td1 = $("<td></td>");
            td1.text('0');
            td1.attr('id', '1tyaku');
            var td2 = $("<td></td>");
            td2.text('0');
            td2.attr('id', '2tyaku');
            var td3 = $("<td></td>");
            td3.text('0');
            td3.attr('id', '3tyaku');
            var td4 = $("<td></td>");
            td4.text('0');
            td4.attr('id', '4tyaku');

            var tdWin = $("<td></td>");
            tdWin.text('0.00');
            tdWin.attr('id', 'win');
            var tdRen = $("<td></td>");
            tdRen.text('0.00');
            tdRen.attr('id', 'ren');
            var tdFuku = $("<td></td>");
            tdFuku.text('0.00');
            tdFuku.attr('id', 'fuku');

            tr.append(tdKey);
            tr.append(td1);
            tr.append(td2);
            tr.append(td3);
            tr.append(td4);
            tr.append(tdWin);
            tr.append(tdRen);
            tr.append(tdFuku);
        } else {
            tr = $("#resultTbl").find('#' + key);
        }

        var kaisu;
        var win;
        var ren;
        var fuku;
        if (value == 0) {
            kaisu = Number(tr.find('#1tyaku').text());
            tr.find('#1tyaku').text(kaisu + 1);
        } else if (value == 1) {
            kaisu = Number(tr.find('#2tyaku').text());
            tr.find('#2tyaku').text(kaisu + 1);
        } else if (value == 2) {
            kaisu = Number(tr.find('#3tyaku').text());
            tr.find('#3tyaku').text(kaisu + 1);
        } else {
            kaisu = Number(tr.find('#4tyaku').text());
            tr.find('#4tyaku').text(kaisu + 1);
        };

        var total = Number(tr.find('#1tyaku').text()) + Number(tr.find('#2tyaku').text()) + Number(tr.find('#3tyaku').text()) + Number(tr.find('#4tyaku').text());
        win = (Number(tr.find('#1tyaku').text()) / total).toFixed(2);
        tr.find('#win').text(win);
        ren = ((Number(tr.find('#1tyaku').text()) + Number(tr.find('#2tyaku').text())) / total).toFixed(2);
        tr.find('#ren').text(ren);
        fuku = ((Number(tr.find('#1tyaku').text()) + Number(tr.find('#2tyaku').text()) + Number(tr.find('#3tyaku').text())) / total).toFixed(2);
        tr.find('#fuku').text(fuku);
    }

    function addResultTableOverlay() {
        // 既存オーバーレイがあれば削除
        $('#resultOverlay').remove();

        const $overlay = $('<div>', {
            id: 'resultOverlay'
        }).append(
            $('<div>', {
                text: '読み込み中…',
                css: {
                    color: '#333',
                    fontSize: '18px',
                    fontWeight: 'bold',
                    textAlign: 'center',
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)'
                }
            })
        );

        $('body').append($overlay);

        const $target = $('#resultTbl');
        const offset = $target.offset();

        $overlay.css({
            position: 'absolute',
            top: offset.top,
            left: offset.left,
            width: $target.outerWidth(),
            height: $target.outerHeight(),
            background: 'rgba(255, 255, 255, 0.8)',
            zIndex: 9999,
            cursor: 'wait'
        });
    }

    function removeResultTableOverlay() {
        $('#resultOverlay').remove();
    }

    (function () {
        'use strict';
        try {
            init();
        } catch (error) {
            console.log(error);
        }
    })();
})(window.jQuery.noConflict(true));