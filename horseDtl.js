// ==UserScript==
// @name         horseDtl
// @namespace    http://tampermonkey.net/
// @version      1.0
// @updateURL   https://raw.githubusercontent.com/fr000456/ore/main/horseDtl.js
// @downloadURL https://raw.githubusercontent.com/fr000456/ore/main/horseDtl.js
// @description  netkeiba馬ページ拡張
// @include      https://db.netkeiba.com/horse/*
// @require      https://code.jquery.com/jquery-3.6.0.min.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/const.js
// @require      https://raw.githubusercontent.com/fr000456/ore/main/common.js
// @grant       GM.xmlHttpRequest
// @connect     localhost
// @connect     127.0.0.1
// @connect      db.netkeiba.com
// ==/UserScript==

var prevDate = null;

function addMark(a, txt, col) {
  var mark = $("<nobr></nobr>", { text: txt }).css("background-color", col);
  a.prepend(mark);
}

function tataki(a, count) {
  var date = a.text().split("/");
  var txt = null;
  var col = null;

  if (prevDate != null) {
    if (kankaku(date, prevDate) < 9) {
      //連闘
      addMark(a, txtRen, colRen);
    } else if (kankaku(date, prevDate) < 17) {
      //中一週
      addMark(a, txtNaka, colNaka);
    }
    if (kankaku(date, prevDate) > 90) {
      txt = txtYa;
      col = colYa;
      count = 0;
    } else if (kankaku(date, prevDate) > 53) {
      //リセット
      count = 0;
    }
  } else {
    txt = txtYa;
    col = colYa;
    count = 0;
  }

  prevDate = date;
  count++;

  if (count == 2) {
    txt = txtNi;
    col = colNi;
  } else if (count == 3) {
    txt = txtSan;
    col = colSan;
  }

  addMark(a, txt, col);

  return count;
}

function hinba(html, a) {
  if ($(".horse_title").find("p").text().indexOf("牝") == -1) {
    return;
  }
  if (
    $("<div>")
      .html(html)
      .find("#hinba")
      .find(".mainrace_data")
      .find('p:contains("牝")').length == 0
  ) {
    return;
  }
  addMark(a, hinTxt, hinCol);
}

function kasoku(html, a) {
  if (
    a
      .closest("tr")
      .find("td:eq(" + tyakuIndex + ")")
      .text() != "1"
  ) {
    return;
  }
  var lapString;
  if ($("<div>").html(html).find("#lap").html().length == 0) {
    return;
  }
  lapString = $("<div>").html(html).find("#lap").html().split("-");

  var lapLength = lapString.length;

  if (Number(lapString[lapLength - 1]) >= Number(lapString[lapLength - 2])) {
    return;
  }
  if (Number(lapString[lapLength - 2]) > Number(lapString[lapLength - 3])) {
    return;
  }

  addMark(a, kasokuTxt, kasokuCol);
}

function kaiseki() {
  var count = 0;
  $($(".db_h_race_results").find("a").get().reverse()).each(function () {
    var horseUrl = $(this).attr("href");
    if (
      horseUrl.indexOf("/race/") == -1 ||
      horseUrl.indexOf("/sum/") != -1 ||
      horseUrl.indexOf("/movie/") != -1
    ) {
      return true;
    }

    var a = $(this);

    //開催日
    if (horseUrl.indexOf("/list/") != -1) {
      count = tataki(a, count);
      return true;
    }

    //牝馬＆一着じゃなかったら終わり
    if (
      $(".horse_title").find("p").text().indexOf("牝") == -1 &&
      a
        .closest("tr")
        .find("td:eq(" + tyakuIndex + ")")
        .text() != "1"
    ) {
      return true;
    }

    ajax(horseUrl).then((html) => {
      hinba(html, a);
      kasoku(html, a);
    });
  });
}

function paceReplace(paceArray) {
  if (paceArray[1] - paceArray[0] > pace1) {
    return (
      '<td><div class="' +
      class1 +
      '" style="display: inline-block;">' +
      paceArray[0] +
      "</div>-" +
      paceArray[1] +
      "</td>"
    );
  } else if (paceArray[1] - paceArray[0] > pace2) {
    return (
      '<td><div class="' +
      class2 +
      '" style="display: inline-block;">' +
      paceArray[0] +
      "</div>-" +
      paceArray[1] +
      "</td>"
    );
  } else if (paceArray[1] - paceArray[0] > 0) {
    return (
      '<td><div class="' +
      class3 +
      '" style="display: inline-block;">' +
      paceArray[0] +
      "</div>-" +
      paceArray[1] +
      "</td>"
    );
  } else if (paceArray[0] - paceArray[1] > pace1) {
    return (
      "<td>" +
      paceArray[0] +
      '-<div class="' +
      class1 +
      '" style="display: inline-block;">' +
      paceArray[1] +
      "</div></td>"
    );
  } else if (paceArray[0] - paceArray[1] > pace2) {
    return (
      "<td>" +
      paceArray[0] +
      '-<div class="' +
      class2 +
      '" style="display: inline-block;">' +
      paceArray[1] +
      "</div></td>"
    );
  } else if (paceArray[0] - paceArray[1] > 0) {
    return (
      "<td>" +
      paceArray[0] +
      '-<div class="' +
      class3 +
      '" style="display: inline-block;">' +
      paceArray[1] +
      "</div></td>"
    );
  } else {
    return "<td>" + paceArray[0] + "-" + paceArray[1] + "</td>";
  }
}

function pace() {
  var pace = $(".db_h_race_results")
    .find("tr:gt(0)")
    .find("td:eq(" + paceIndex + ")");
  for (var i = 0; i < pace.length; i++) {
    pace.eq(i).replaceWith(paceReplace(pace.eq(i).text().split("-")));
  }
}

function hideTr(colId, colIndex) {
  var col = $("#" + colId).val();
  if (col == "") {
    return;
  }
  $(".db_h_race_results")
    .find("tr:gt(0)")
    .find("td:eq(" + colIndex + "):not(:contains(" + col + "))")
    .closest("tr")
    .hide();
}

function refine() {
  $(".db_h_race_results").find("tr").show();
  hideTr("kaisai", corseIndex);
  hideTr("race", raceIndex);
  hideTr("kisyu", kisyuIndex);
  hideTr("kyori", kyoriIndex);
}

function sonogoTotal() {
  $(".db_h_race_results")
    .find("tbody")
    .find("tr")
    .each(function (index) {
      var a = $(this).find("td").eq(raceIndex).find("a");
      changeSonogoFunc(a, index);
    });
}

function addTotalButton() {
  $(".db_h_race_results")
    .find("tbody")
    .find("tr")
    .each(function (index) {
      var a = $(this).find("td").eq(eizouIndex).find("a");
      var race = $(this).find("td").eq(raceIndex).find("a");
      var button = $("<input>", {
        type: "button",
        style: "height:12px",
        value: "　　",
        id: "sonogoButton" + index,
      });
      button.bind("click", function () {
        $(this).attr("disabled", true);
        changeSonogoFunc(race, index);
      });
      a.replaceWith(button);
    });
}

function addTukaButton() {
  $(".db_h_race_results")
    .find("tbody")
    .find("tr")
    .each(function (index) {
      var time = $(this).find("td").eq(timeIndex);
      var race = $(this).find("td").eq(raceIndex).find("a");
      var button = $("<input>", {
        type: "button",
        style: "height:12px",
        value: "　",
        id: "tukaButton" + index,
      });
      button.bind("click", function () {
        tukaOpen(race.attr("href"), index);
      });
      time.replaceWith($("<td>").append(button));
    });
}

function tukaOpen(receUrl, index) {
  ajax(receUrl).then(function (raceHtml) {
    //通過部分を書き換え
    var tr = $(".db_h_race_results").find("tbody").children("tr").eq(index);
    var tuka = tr.find("td").eq(tuukaIndex);
    var raceTable = $(raceHtml).find("#raceResult");
    var tukaRaceTable = tuka.find(".race_table_01");
    if (tukaRaceTable.length == 0) {
      raceTable.find("tr:gt(5)").remove();
      raceTable.find("tr").eq(0).remove();
      raceTable.find("tr").find("td:lt(14)").remove();
      raceTable.find("tr").find("td:gt(1)").remove();
      tuka.append(raceTable);
    } else {
      tuka.find(".race_table_01").remove();
    }
  });
}

function refineKaisai(e) {
  //コース
  //解除 w=87
  //中京 c=67
  //中山 n=78
  //東京 t=84
  //京都 k=75
  //阪神 h=72
  //福島 f=70
  //函館 a=65
  //札幌 p=80
  //小倉 r=82
  //新潟 g=71

  //ダート d=68
  //芝 s=83

  if (e.keyCode == 67) {
    $("#kaisai").val("中京");
    refine();
  } else if (e.keyCode == 78) {
    $("#kaisai").val("中山");
    refine();
  } else if (e.keyCode == 84) {
    $("#kaisai").val("東京");
    refine();
  } else if (e.keyCode == 75) {
    $("#kaisai").val("京都");
    refine();
  } else if (e.keyCode == 72) {
    $("#kaisai").val("阪神");
    refine();
  } else if (e.keyCode == 70) {
    $("#kaisai").val("福島");
    refine();
  } else if (e.keyCode == 65) {
    $("#kaisai").val("函館");
    refine();
  } else if (e.keyCode == 80) {
    $("#kaisai").val("札幌");
    refine();
  } else if (e.keyCode == 82) {
    $("#kaisai").val("小倉");
    refine();
  } else if (e.keyCode == 71) {
    $("#kaisai").val("新潟");
    refine();
  } else if (e.keyCode == 87) {
    $("#kaisai").val("");
    $("#kyori").val("");
    refine();
  } else if (e.keyCode == 68) {
    $("#kyori").val("ダ" + $("#kyori").val());
    refine();
  } else if (e.keyCode == 83) {
    $("#kyori").val("芝" + $("#kyori").val());
    refine();
  }

  //距離
  else if (e.keyCode == 49) {
    $("#kyori").val("1000");
    refine();
  } else if (e.keyCode == 50) {
    $("#kyori").val("1200");
    refine();
  } else if (e.keyCode == 51) {
    $("#kyori").val("1300");
    refine();
  } else if (e.keyCode == 52) {
    $("#kyori").val("1400");
    refine();
  } else if (e.keyCode == 53) {
    $("#kyori").val("1600");
    refine();
  } else if (e.keyCode == 54) {
    $("#kyori").val("1700");
    refine();
  } else if (e.keyCode == 55) {
    $("#kyori").val("1800");
    refine();
  } else if (e.keyCode == 56) {
    $("#kyori").val("1900");
    refine();
  } else if (e.keyCode == 57) {
    $("#kyori").val("2000");
    refine();
  } else if (e.keyCode == 48) {
    $("#kyori").val("2200");
    refine();
  } else if (e.keyCode == 173) {
    $("#kyori").val("2400");
    refine();
  } else if (e.keyCode == 160) {
    $("#kyori").val("2500");
    refine();
  } else if (e.keyCode == 220) {
    $("#kyori").val("3000");
    refine();
  } else if (e.keyCode == 74) {
    $("#kyori").val("障");
    refine();
  } else if (e.keyCode == 8) {
    $("#kyori").val("");
    refine();
  }
}

function refineKyori(e) {
  //距離
  if (e.keyCode == 96) {
    $("#kyori").val("1200");
    refine();
  } else if (e.keyCode == 97) {
    $("#kyori").val("1400");
    refine();
  } else if (e.keyCode == 98) {
    $("#kyori").val("1600");
    refine();
  } else if (e.keyCode == 99) {
    $("#kyori").val("1800");
    refine();
  } else if (e.keyCode == 100) {
    $("#kyori").val("2000");
    refine();
  } else if (e.keyCode == 101) {
    $("#kyori").val("2200");
    refine();
  } else if (e.keyCode == 102) {
    $("#kyori").val("2400");
    refine();
  } else if (e.keyCode == 103) {
    $("#kyori").val("3000");
    refine();
  } else if (e.keyCode == 104) {
    $("#kyori").val("3200");
    refine();
  } else if (e.keyCode == 87) {
    $("#kyori").val("");
    refine();
  }
}

(function () {
  "use strict";

  const waitForTable = setInterval(() => {
    const $table = $(".db_main_deta");
    const $dateTh = $('th:contains("日付")');

    if ($table.length && $dateTh.length) {
      clearInterval(waitForTable);

      setIndex($table);

      // ヘッダ書き換え → この時点でボタンがDOM上に出現する
      $('th:contains("日付")').replaceWith(
        '<th><input type="button" value="絞り込み" id="refine"></th>',
      );
      $('th:contains("開催")').replaceWith(
        '<th><input placeholder="開催" type="text" id="kaisai" size="2"></th>',
      );
      $('th:contains("レース名")').replaceWith(
        '<th><input placeholder="レース名" type="text" id="race" size="3"></th>',
      );
      $('th:contains("騎手")').replaceWith(
        '<th width="300px"><input placeholder="騎手" type="text" id="kisyu" size="2"></th>',
      );
      $(".db_h_race_results")
        .find('th:contains("距離")')
        .replaceWith(
          '<th><input placeholder="距離" type="text" id="kyori" size="2"></th>',
        );
      $('th:contains("映像")').replaceWith(
        '<th><input type="button" value="その後" id="sonogo"></th>',
      );

      // ✅ ボタンがDOM上に現れた後にイベント登録する！
      $("#refine").on("click", function () {
        refine();
      });
      $("#sonogo").on("click", function () {
        sonogoTotal();
      });

      // キーショートカットも on で
      $(window).on("keydown", function (e) {
        if (e.shiftKey) {
          e.preventDefault();
          refineKaisai(e);
        } else if (e.altKey) {
          e.preventDefault();
          refineKyori(e);
        }
      });

      // その他処理
      pace();
      addTotalButton();
      addTukaButton();
      kaiseki();
    }
  }, 300);
})();
