// ==UserScript==
// @name         kaiseki
// @namespace    http://tampermonkey.net/
// @version      0.1
// @match        https://race.netkeiba.com/race/shutuba.html*
// @match        https://nar.netkeiba.com/race/shutuba.html*
// @match        https://race.netkeiba.com/race/shutuba_abroad.html*
// @run-at       document-idle
// @grant       GM.xmlHttpRequest
// @connect     localhost
// @connect     127.0.0.1
// @require https://code.jquery.com/jquery-3.6.0.min.js
// @require https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js
// @require https://gist.githubusercontent.com/fr000456/d9c0f4a161df409d303683b51410b619/raw/1e7b38b633ac5700d99ded1254570ad7069e93b6/const
// @require https://gist.githubusercontent.com/fr000456/cc4230bcd2f1da38e70d65fffb46c73a/raw/c972fa7c3eeff4ffec5cee4ddbd7c2aa8a0346a1/common
// @require https://gist.githubusercontent.com/fr000456/84bbff4bc370aba05010f53380597adb/raw/c9c60d6a820571616b4bfcfbd74849ce5fc895f1/html
// ==/UserScript==

(function ($) {
  if (window.__kaisekiInitDone) return;
  window.__kaisekiInitDone = true;

  // DOM揃ったら初期化
  function waitForElement(selector, callback, interval = 100, timeout = 5000) {
    const start = Date.now();
    const timer = setInterval(() => {
      if ($(selector).length) {
        clearInterval(timer);
        callback();
      } else if (Date.now() - start > timeout) {
        clearInterval(timer);
        console.warn("waitForElement timeout: " + selector);
      }
    }, interval);
  }

  async function kaiseki(aFunc) {
    const a = $(".HorseName").find("a");

    const promises = [];

    for (let index = 0; index < a.length; index++) {
      const horse = a.eq(index);
      const href = horse.attr("href");
      const match = href.match(/horse\/([A-Za-z0-9\-]+)/);

      if (!match) continue;

      const horseId = match[1].trim();

      const p = getHtmlFromMap(horseId).then((html) => {
        if (!html) return;

        setIndex(html);

        return aFunc(html, horse, index);
      });

      promises.push(p);
    }

    await Promise.all(promises);

    changeCss();
  }

  // ページ初期化
  function initPageWrapper() {
    try {
      initPage(); // あなたの initPage 関数
    } catch (e) {
      console.error("initPage error:", e);
    }
  }

  waitForElement("#AllRaceSubMenu, #shutuba_menu", initPageWrapper);

  var prevDate = null;
  var kyoriVal = null;
  var corseVal = null;

  //functionたち
  var initFunc = function (html, a, index) {
    changeTableDtl(a, index);
  };

  var funcKaiseki = function (html, a, index) {
    doKaiseki(html, a);
  };

  var funcTekisei = function (html, a, index) {
    setVal();
    tekisei(html, index);
    return Promise.resolve();
  };

  var funcBaba = function (html, a, index) {
    babakaiseki(html, a, index);
  };

  var funcRota = function (html, a, index) {
    rotation(html, a, index);
  };

  var funcUchi = function (html, a, index) {
    uchimawari(html, index);
  };

  var funcBikou = function (html, a, index) {
    bikou(html, index);
  };

  function rota() {
    kaiseki(funcRota);
  }

  function kettou() {
    kaiseki(kettouFunc);
  }

  function baba() {
    kaiseki(funcBaba);
  }

  function uchi() {
    kaiseki(funcUchi);
  }

  function biko() {
    kaiseki(funcBikou);
  }

  //css
  var horseCss = {
    "border-collapse": "separate",
    "border-spacing": "1px",
    border: "solid 1px #999",
    padding: "1px 3px",
    "line-height": "1.5",
    width: "auto",
    height: "auto",
    "font-size": "13px",
    "white-space": "nowrap",
  };

  var hoverCss = {
    "font-size": "20px",
    background: "#fdf2c1",
    border: "2px solid #fdf2c1",
  };

  function initPage() {
    //ボタン追加
    addButton();
    //イベント追加
    bindFunc();
    //定数設定
    setConst();
    //変数設定
    setVal();
    changeTableHd();
    kaiseki(initFunc);

    //とりあえず
    $("#AllRaceSubMenu").append(
      '<input type="button" value="HTMLキャッシュ破棄" id="clearHorseCache">',
    );
    $("#clearHorseCache").on("click", () => {
      const count = Object.keys(horseHtmlCache).length;

      for (const k in horseHtmlCache) {
        delete horseHtmlCache[k];
      }

      console.log(`🗑️ horseHtmlCache を ${count} 件削除`);
      alert(`horseHtmlCache を ${count} 件削除しました`);
    });
  }

  function setVal() {
    kyoriVal = $("#kyori").val();
    corseVal = $("#corse").val();
  }

  function changeCss() {
    $(".HorseList td").css(horseCss);
    // $('tr.HorseList').removeClass('HorseList');
    $(".HorseInfo").removeClass("HorseInfo");
    // $('.Selected').removeClass('Selected');
    // $('.NoSelected').removeClass('NoSelected');
    $(".Jockey").removeClass("Jockey");
    $(".Trainer").removeClass("Trainer");
    // $('.Popular').removeClass("Popular");
    $(".selectBox").removeClass("selectBox");

    $(".Shutuba_Table")
      .find("tbody")
      .find("tr")
      .mouseover(function () {
        $(".Selected").removeClass("Selected");
        $(this).attr("style", "background-color:#C2EEFF");
        //$(this).attr("style","background-color:#fdf2c1");
      });
    $(".Shutuba_Table")
      .find("tbody")
      .find("tr")
      .mouseout(function () {
        $(this).attr("style", "background-color:");
      });
  }

  function bindFunc() {
    $("#kaiseki").bind("click", function () {
      kaiseki(funcKaiseki);
    });
    $("#baba").bind("click", function () {
      baba();
    });
    $("#tekisei").bind("click", function () {
      kaiseki(funcTekisei);
    });
    $("#kettou").bind("click", function () {
      kettou();
    });
    $("#rota").bind("click", function () {
      rota();
    });
    $("#uchi").bind("click", function () {
      uchi();
    });
    $("#bikou").bind("click", function () {
      biko();
    });

    //血統初期値
    $("#AllRaceSubMenu")
      .append('<input type="button" value="ボールドルーラ―" id="bold">')
      .append('<input type="button" value="Vice Regent" id="vice">')
      .append('<input type="button" value="Danzig" id="danzig">');

    $("#kettou").bind("click", function () {
      kettou();
    });
    $("#bold").bind("click", function () {
      bold();
    });
    $("#vice").bind("click", function () {
      vice();
    });
    $("#danzig").bind("click", function () {
      danzig();
    });
  }

  function bold() {
    $("#kettou1").val("Secretariat");
    $("#kettou2").val("Storm");
    kettou();
  }

  function vice() {
    $("#kettou1").val("Vice Regent");
    $("#kettou2").val("");
    kettou();
  }

  function danzig() {
    $("#kettou1").val("Danzig");
    $("#kettou2").val("Nijinsky");
    kettou();
  }

  function setConst() {
    //コース
    if ($(".RaceData01").find('span:contains("障")').length > 0) {
      course = "障";
    } else if ($(".RaceData01").find('span:contains("芝")').length > 0) {
      course = "芝";
    } else if ($(".RaceData01").find('span:contains("ダ")').length > 0) {
      course = "ダ";
    }
  }

  function rotation(html, a, index) {
    var data = $("<div>").html(html).find("#data").find("tbody").find("tr");

    var yasumi = [0, 0, 0, 0];
    var futu = [0, 0, 0, 0];
    var ni = [0, 0, 0, 0];
    var san = [0, 0, 0, 0];
    var tukai = [0, 0, 0, 0];
    var count = 0;
    var pDate = null;

    for (var i = data.length - 1; i >= 0; i--) {
      var tr = data.eq(i);
      var date = tr
        .find("td")
        .eq(hidukeIndex)
        .text()
        .trim()
        .slice(-10)
        .split("/");

      if (pDate != null) {
        if (kankaku(date, pDate) > 90) {
          //リセット
          count = 0;
          yasumi = getTyakujun(yasumi, tr);
        } else if (kankaku(date, pDate) > 53) {
          count = 0;
          futu = getTyakujun(futu, tr);
        }
      } else {
        yasumi = getTyakujun(yasumi, tr);
      }

      if (count == 1) {
        ni = getTyakujun(ni, tr);
      } else if (count == 2) {
        san = getTyakujun(san, tr);
      } else if (count > 2) {
        tukai = getTyakujun(tukai, tr);
      }

      count++;
      pDate = date;
    }

    switch (a.find("#tataki").val()) {
      case "0":
        addSeiseki($("#rotaTd" + index), futu);
        break;
      case "1":
        addSeiseki($("#rotaTd" + index), yasumi);
        break;
      case "2":
        addSeiseki($("#rotaTd" + index), ni);
        break;
      case "3":
        addSeiseki($("#rotaTd" + index), san);
        break;
      case "4":
        addSeiseki($("#rotaTd" + index), tukai);
        break;
    }
  }

  function addTatakiHtml(a, tatakiFlg) {
    var tatakiHidden = $("<input></input>", {
      type: "hidden",
      id: "tataki",
      value: tatakiFlg,
    });
    a.append(tatakiHidden);
  }

  function babakaiseki(html, a, index) {
    var data = $("<div>").html(html).find("#data").find("tbody").find("tr");

    var seisekiVal = [0, 0, 0, 0];
    var babaVal = ["", "", "", ""];

    if ($("#ryou").prop("checked")) {
      babaVal[0] = "良";
    }
    if ($("#yaya").prop("checked")) {
      babaVal[1] = "稍";
    }
    if ($("#omo").prop("checked")) {
      babaVal[2] = "重";
    }
    if ($("#fu").prop("checked")) {
      babaVal[3] = "不";
    }

    seisekiVal = getSeisekiVal(data, babaIndex, babaVal);
    addSeiseki($("#babaTd" + index), seisekiVal);
  }

  function uchimawari(html, index) {
    var data = $("<div>").html(html).find("#data").find("tbody").find("tr");

    if (data.length == 0) {
      return false;
    }

    var seisekiVal = [0, 0, 0, 0];

    for (var i = 0; i < corseUchi.length; i++) {
      var tgtTr = data
        .find("td:eq(" + corseIndex + "):contains(" + corseUchi[i][0] + ")")
        .parent()
        .find("td:eq(" + kyoriIndex + "):contains(" + corseUchi[i][1] + ")")
        .parent();
      for (var j = 0; j < tgtTr.length; j++) {
        seisekiVal = getTyakujun(seisekiVal, tgtTr.eq(j));
      }
    }

    addSeiseki($("#corseTd" + index), seisekiVal);
  }

  function bikou(html, index) {
    var data = $("<div>").html(html).find("#data").find("tbody").find("tr");
    if (data.length == 0) {
      return false;
    }

    var td = data.find("td");
    var bikouVal = td.eq(bikouIndex).html();

    $("#bikouTd" + index).text(bikouVal.replace(/&nbsp;/g, ""));
  }

  function tekisei(html, index) {
    var data = $("<div>").html(html).find("#data").find("tbody").find("tr");

    if (data.length == 0) {
      return false;
    }
    var seisekiVal = [0, 0, 0, 0];

    var hidariSeisekiVal = getSeisekiVal(data, corseIndex, corseHidari);
    //左回り
    if (corseHidari.includes(corseVal)) {
      addSeiseki($("#hidariTd" + index), hidariSeisekiVal);
    } else {
      //右回り
      seisekiVal = getSeisekiValNot(data, corseIndex, hidariSeisekiVal);
      addSeiseki($("#migiTd" + index), seisekiVal);
    }
    //コース
    seisekiVal = getSeisekiVal(data, corseIndex, [corseVal]);
    addSeiseki($("#corseTd" + index), seisekiVal);

    //距離
    seisekiVal = getSeisekiVal(data, kyoriIndex, [kyoriVal]);
    addSeiseki($("#kyoriTd" + index), seisekiVal);

    //両方
    seisekiVal = getMultiSeisekiVal(
      data,
      corseIndex,
      kyoriIndex,
      corseVal,
      kyoriVal,
    );
    addSeiseki($("#ryouTd" + index), seisekiVal);

    //通過順
    addTuuka($("#tuukaTd" + index), data);
  }

  function addTuuka(tgt, data) {
    var td = $(data).eq(0).find("td");
    var tuukaVal = td.eq(tuukaIndex).html();
    var color = td.eq(agariIndex).attr("class");

    if (color?.trim() == "rank_1") {
      tgt.text(tuukaVal).addClass(classR1ml);
    } else if (color?.trim() == "rank_2") {
      tgt.text(tuukaVal).addClass(classR2ml);
    } else if (color?.trim() == "rank_3") {
      tgt.text(tuukaVal).addClass(classR3ml);
    } else {
      tgt.text(tuukaVal);
    }
  }

  function tataki(data) {
    var ren = 1;
    for (var index = 0; index < 4; index++) {
      if (index == data.length) {
        return 0;
      }
      var tr = data.eq(index);
      var date = tr
        .find("td")
        .eq(hidukeIndex)
        .text()
        .trim()
        .slice(-10)
        .split("/");

      if (index == 0) {
        //前走
        if (kankaku(prevDate, date) < 9) {
          //連闘
          ren = -1;
        } else if (kankaku(prevDate, date) < 17) {
          //中一週
          ren = 10;
        }
        if (kankaku(prevDate, date) > 90) {
          //休み明け
          return 1;
        } else if (kankaku(prevDate, date) > 60) {
          //なんもなし
          return 0;
        }
      } else {
        //前々走 or 前々々走
        if (kankaku(prevDate, date) > 53) {
          //叩き二走目 or 三走目
          return (index + 1) * ren;
        }
      }
      prevDate = date;
    }
    return index * ren;
  }

  function syoukyu(data) {
    //前走が1着
    if (data.eq(0).find("td").eq(tyakuIndex).text() == "1") {
      return false;
    }
    //前々走がＯＰ以上
    if (getRank(data.eq(1).find("td").eq(raceIndex).text()) > 4) {
      return false;
    }
    //前々走が1着以外
    if (data.eq(1).find("td").eq(tyakuIndex).text() != "1") {
      return false;
    }
    return true;
  }

  function kyori(data) {
    var kyoriStr = $(".RaceData01").find("span").eq(0).text().slice(1, -1);
    //前走が同距離ではない
    if (data.eq(0).find("td").eq(kyoriIndex).text() != kyoriStr) {
      return false;
    }
    //二戦以上経験している
    if (
      data.find("td:eq(" + kyoriIndex + "):contains(" + kyoriStr + ")").length >
      1
    ) {
      return false;
    }
    return true;
  }

  function syougai(data) {
    //そもそも障害レースではない
    if (course != "障") {
      return false;
    }
    return data.find("td:eq(" + kyoriIndex + "):contains(障)").length == 1;
  }

  function dirt(data) {
    //そもそもダートレースではない
    if (course != "ダ") {
      return false;
    }
    return data.find("td:eq(" + kyoriIndex + "):contains(ダ)").length == 1;
  }

  function hatsu(data) {
    return (
      data.find("td:eq(" + kyoriIndex + "):contains(" + course + ")").length ==
      0
    );
  }

  function getRaceDate() {
    var title = $("title").text();
    var year = title.substr(title.lastIndexOf("年") - 4, 4);
    var month = title.slice(
      title.lastIndexOf("年") + 1,
      title.lastIndexOf("月"),
    );
    var date = title.slice(
      title.lastIndexOf("月") + 1,
      title.lastIndexOf("日"),
    );

    return [year, month, date];
  }

  function doKaiseki(html, a) {
    var data = $("<div>").html(html).find("#data").find("tbody").find("tr");

    var hatsuFlg = true;
    var syougaiFlg = false;
    var tatakiFlg = -1;
    var dirtFlg = false;
    var syoukyuFlg = false;
    var kyoriFlg = false;

    prevDate = getRaceDate(); //レース当日

    a.find("td").remove();
    a.find("img").remove();

    if (data.length == 0) {
      addMark(a, txtHatsu, colHatsu);
      banushi(html, a);
      return false;
    }

    //初コース
    hatsuFlg = hatsu(data);
    //ダート二戦目
    dirtFlg = dirt(data);
    //障害二戦目
    syougaiFlg = syougai(data);

    var size = data.length;
    //昇級二戦目
    if (size > 1) {
      syoukyuFlg = syoukyu(data);
    }
    //距離二戦目
    kyoriFlg = kyori(data);
    //叩き
    tatakiFlg = tataki(data);

    if (syougaiFlg) {
      addMark(a, txtSyougai, colSyougai);
    }
    if (kyoriFlg) {
      addMark(a, txtKyori, colKyori);
    }
    if (tatakiFlg < 0) {
      addMark(a, txtRen, colRen); //連闘
      tatakiFlg = tatakiFlg * -1;
    }
    if (tatakiFlg > 9) {
      addMark(a, txtNaka, colNaka); //中一週
      tatakiFlg = tatakiFlg / 10;
    }
    switch (tatakiFlg) {
      case 0:
        break; //なんもなし
      case 1:
        addMark(a, txtYa, colYa);
        break; //休み明け
      case 2:
        addMark(a, txtNi, colNi);
        break; //二走目
      case 3:
        addMark(a, txtSan, colSan);
        break; //三走目
    }
    addTatakiHtml(a, tatakiFlg);
    if (syoukyuFlg) {
      addMark(a, txtSyo, colSyo);
    }
    if (hatsuFlg) {
      addMark(a, txtHatsu, colHatsu);
    }
    if (dirtFlg) {
      addMark(a, txtDa, colDa);
    }

    banushi(html, a);
  }
})(jQuery);
