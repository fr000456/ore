function addButton() {
  var kaisekiUl = $("<ul></ul>", { id: "kaisekiUl" }).addClass("RaceSubMenu");
  if ($("#AllRaceSubMenu").length > 0) {
    $("#AllRaceSubMenu").append("<br>").append(kaisekiUl);
  } else {
    $("#shutuba_menu").append("<br>").append(kaisekiUl);
  }

  //解析ボタン
  kaisekiUl
    .append('<li><input type="button" value="解析" id="kaiseki"></li>')
    //血統
    .append("<br><br>")
    .append(
      '<li><input type="checkbox" id="kettouAll" value = "kettouAll">全</li>',
    )
    .append(
      '<li><input placeholder="血統1" type="text" id="kettou1" size="6"></li>',
    )
    .append(
      '<li><input placeholder="血統2" type="text" id="kettou2" size="6"></li>',
    )
    .append('<li><input type="button" value="血統" id="kettou"></li>')
    //馬場
    .append('<li><input type="checkbox" id="ryou" value = "ryou">良</li>')
    .append('<li><input type="checkbox" id="yaya" value = "yaya">稍</li>')
    .append('<li><input type="checkbox" id="omo" value = "omo">重</li>')
    .append('<li><input type="checkbox" id="fu" value = "fu">不</li>')
    .append('<li><input type="button" value="馬場" id="baba"></li>')
    //適正ボタン
    .append(
      '<li><input placeholder="コース" type="text" id="corse" size="3"></li>',
    )
    .append(
      '<li><input placeholder="距離" type="text" id="kyori" size="3"></li>',
    )
    .append('<li><input type="button" value="適性" id="tekisei"></li>')
    .append('<li><input type="button" value="内回り" id="uchi"></li>')
    //ローテ
    .append('<li><input type="button" value="ローテ" id="rota"></li>')
    //備考
    .append('<li><input type="button" value="備考" id="bikou"></li>');
  //初期値
  $("#corse").val($(".RaceData02").find("span").eq(1).text());
  $("#kyori").val($(".RaceData01").find("span").eq(0).text().substr(1, 5));
}

function changeTableHd() {
  var tuukaTh = $("<th>", { text: "通過順" });
  var corseTh = $("<th>", { text: "コース" });
  var kyoriTh = $("<th>", { text: "距離" });
  var ryouTh = $("<th>", { text: "両方" });
  var hidariTh = $("<th>", { text: "左" });
  var migiTh = $("<th>", { text: "右" });
  var rotaTh = $("<th>", { text: "ローテ" });
  var babaTh = $("<th>", { text: "馬場" });
  var bikouTh = $("<th>", { text: "備考" });

  var table = $(".RaceTableArea");

  table.find(".FavHorse").remove();

  var memoTh = table.find('th:contains("メモ")').eq(0);
  var headers = [
    tuukaTh,
    bikouTh,
    babaTh,
    rotaTh,
    hidariTh,
    migiTh,
    corseTh,
    kyoriTh,
    ryouTh,
  ];
  headers.forEach((th) => {
    memoTh.after(th);
    memoTh = th;
  });

  table.find('th:contains("メモ")').remove();
  $(".FavHorseSub").remove();
  $(".FavRegist").remove();
  $(".FavMemo").remove();
}

function changeTableDtl(a, index) {
  if ($("#corseTd" + index).length != 0) {
    return;
  }

  const tr = a.closest("tr"); // ← 1回だけ取得

  var tuukaTd = $("<td>", { id: "tuukaTd" + index });
  var corseTd = $("<td>", { id: "corseTd" + index });
  var kyoriTd = $("<td>", { id: "kyoriTd" + index });
  var ryouTd = $("<td>", { id: "ryouTd" + index });
  var hidariTd = $("<td>", { id: "hidariTd" + index });
  var migiTd = $("<td>", { id: "migiTd" + index });
  var rotaTd = $("<td>", { id: "rotaTd" + index });
  var babaTd = $("<td>", { id: "babaTd" + index });
  var bikouTd = $("<td>", { id: "bikouTd" + index });

  tr.find("td:last").remove();
  tr.find("td:last").remove();

  tr.append(
    tuukaTd,
    bikouTd,
    babaTd,
    rotaTd,
    hidariTd,
    migiTd,
    corseTd,
    kyoriTd,
    ryouTd,
  );
}

function changeResultTableHd() {
  var sonogoTh = $("<th>", { text: "その後" });
  var table = $(".race_table_01");
  table.find('th:contains("馬名")').after(sonogoTh);
}

function changeResultTableDtl(a, index) {
  var sonogoTd = $("<td>", { id: "sonogoTd" + index });
  a.closest("td").after(sonogoTd);
}
