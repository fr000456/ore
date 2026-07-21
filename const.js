//定数
var kettouColor = "violet";
var kettou2Color = "lightsteelblue";
var kettou3Color = "yellow";

var classR1ml = "BgYellow";
var classR2ml = "BgBlue02";
var classR3ml = "BgOrange";

var corseHidari = ["東京", "中京", "新潟", "盛岡", "船橋", "浦和", "川崎"];
var raceRank = [
  ["新馬", 0],
  ["未勝利", 1],
  ["1勝", 2],
  ["500万", 2],
  ["2勝", 3],
  ["1000万", 3],
  ["3勝", 4],
  ["1600万", 4],
  ["OP", 5],
  ["L", 6],
  ["GIII", 7],
  ["GII", 8],
  ["GI", 9],
];
var corseUchi = [
  ["中山", "芝1800"],
  ["中山", "芝2000"],
  ["中山", "芝2500"],
  ["中山", "芝3200"],
  ["阪神", "芝1200"],
  ["阪神", "芝1400"],
  ["阪神", "芝2000"],
  ["阪神", "芝2200"],
  ["阪神", "芝3000"],
  ["京都", "芝1200"],
  ["京都", "芝2000"],
  ["京都", "芝2200"],
  ["京都", "芝3000"],
  ["新潟", "芝1200"],
  ["新潟", "芝1400"],
  ["新潟", "芝2200"],
  ["新潟", "芝2400"],
];
var corseJRA = [
  "東京",
  "中京",
  "新潟",
  "中山",
  "福島",
  "函館",
  "札幌",
  "阪神",
  "京都",
  "小倉",
];

var colDa = "gold";
var colSyo = "hotpink";
var colYa = "tomato";
var colNi = "springgreen";
var colSan = "springgreen";
var colSyougai = "burlywood";
var colHatsu = "silver";
var colKyori = "aqua";
var colRen = "tan";
var colNaka = "tan";

var txtDa = "ダ";
var txtSyo = "昇";
var txtYa = "休";
var txtNi = "２";
var txtSan = "３";
var txtSyougai = "障";
var txtHatsu = "初";
var txtKyori = "距";
var txtRen = "連";
var txtNaka = "中1";

const hinTxt = "牝";
const hinCol = "pink";
const kasokuTxt = "加";
const kasokuCol = "yellow";

const pace1 = 1.5;
const pace2 = 1;
const pace3 = 0.5;
const class1 = "r1ml";
const class2 = "r2ml";
const class3 = "r3ml";

var kyoriIndex = null;
var corseIndex = null;
var tyakuIndex = null;
var babaIndex = null;
var agariIndex = null;
var tuukaIndex = null;
var raceIndex = null;
var hidukeIndex = 0;
var kisyuIndex = null;
var paceIndex = null;
var eizouIndex = null;
var timeIndex = null;

var course = null;

var raceDate = null;

function getIndex(html, colName) {
  return $(html)
    .find(".db_h_race_results")
    .find("th:contains(" + colName + ")")
    .index();
}

function setIndex(html) {
  //一回だけ
  if (kyoriIndex != null && kyoriIndex > 0) {
    return;
  }
  kyoriIndex = 14; //getIndex(html,"距離");
  tyakuIndex = getIndex(html, "着順");
  raceIndex = getIndex(html, "レース名");
  corseIndex = 1; //getIndex(html,"開催");
  babaIndex = getIndex(html, "馬場");
  agariIndex = getIndex(html, "上り");
  tuukaIndex = getIndex(html, "通過");
  kisyuIndex = getIndex(html, "騎手");
  paceIndex = getIndex(html, "ペース");
  bikouIndex = getIndex(html, "備考");
  eizouIndex = getIndex(html, "映像");
  timeIndex = getIndex(html, "ﾀｲﾑ指数");
}
