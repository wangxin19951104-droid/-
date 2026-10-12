"""Read spreadsheet briefs without adding dependencies to the desktop app."""
import csv
import io
import json
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_COLUMNS = 256


def column_name(index):
    result = ""
    while index:
        index, letter = divmod(index - 1, 26)
        result = chr(65 + letter) + result
    return result


def cell_column(reference):
    match = re.fullmatch(r"([A-Za-z]+)[1-9][0-9]*", reference)
    if not match:
        raise ValueError("Excel 中的单元格位置无效。")
    index = 0
    for letter in match.group(1).upper():
        index = index * 26 + ord(letter) - 64
    if index > MAX_COLUMNS:
        raise ValueError("表格超过 256 列，请只保留与创作有关的列后上传。")
    return index


class TableText:
    def __init__(self, limit):
        self.limit = limit
        self.parts = []
        self.length = 0

    def add(self, text):
        self.length += len(text) + (1 if self.parts else 0)
        self.parts.append(text)
        # Return one extra character so store_script can report clipping.
        return self.length <= self.limit

    def text(self):
        return "\n".join(self.parts)[:self.limit + 1]


def format_row(number, values):
    cells = [column_name(index) + "=" + json.dumps(str(value), ensure_ascii=False)
             for index, value in sorted(values.items()) if str(value).strip()]
    return "第" + str(number) + "行：" + " | ".join(cells) if cells else ""


def decode_table(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("表格编码无法识别，请另存为 UTF-8 CSV 后上传。")


def read_delimited(raw, suffix, limit):
    text = decode_table(raw)
    delimiter = "\t" if suffix == ".tsv" else None
    # Excel sometimes prefixes CSV with its chosen separator.
    first, _, remaining = text.partition("\n")
    if re.fullmatch(r"sep=.", first.strip(), re.IGNORECASE):
        delimiter = first.strip()[-1]
        text = remaining
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    result = TableText(limit)
    result.add("【表格内容】列字母表示原表列位置；首行可能是列标题。")
    count = 0
    try:
        for number, row in enumerate(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter), 1):
            while row and not row[-1].strip():
                row.pop()
            if len(row) > MAX_COLUMNS:
                raise ValueError("表格超过 256 列，请只保留与创作有关的列后上传。")
            line = format_row(number, dict(enumerate(row, 1)))
            if not line:
                continue
            count += 1
            if not result.add(line):
                break
    except csv.Error as exc:
        raise ValueError("表格内容无法读取，请重新导出 CSV 后上传。") from exc
    return result.text() if count else ""


def read_xlsx(raw, limit):
    result = TableText(limit)
    count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_TOTAL_BYTES:
                raise ValueError("Excel 文件解压后过大，请拆分工作表后上传。")

            def xml(name):
                if archive.getinfo(name).file_size > MAX_XML_BYTES:
                    raise ValueError("Excel 工作表过大，请拆分后上传。")
                payload = archive.read(name)
                if b"<!DOCTYPE" in payload or b"<!ENTITY" in payload:
                    raise ValueError("Excel 文件格式不受支持，请另存为 .xlsx 后上传。")
                return ET.fromstring(payload)

            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                for item in xml("xl/sharedStrings.xml").findall(NS + "si"):
                    shared.append("".join(node.text or "" for node in item.iter(NS + "t")))
            relationships = {}
            for item in xml("xl/_rels/workbook.xml.rels"):
                if item.get("TargetMode") != "External":
                    relationships[item.get("Id")] = item.get("Target", "")
            sheets = xml("xl/workbook.xml").find(NS + "sheets")
            if sheets is None:
                return ""
            for sheet in sheets:
                target = relationships.get(sheet.get(RID))
                if not target:
                    continue
                sheet_path = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                                else posixpath.join("xl", target))
                if not sheet_path.startswith("xl/"):
                    raise ValueError("Excel 工作表路径无效，请另存为 .xlsx 后上传。")
                root = xml(sheet_path)
                data = root.find(NS + "sheetData")
                if data is None:
                    continue
                if not result.add("【工作表：" + json.dumps(sheet.get("name", "工作表"), ensure_ascii=False) + "】"):
                    return result.text()
                for ordinal, row in enumerate(data.findall(NS + "row"), 1):
                    values = {}
                    next_column = 1
                    for cell in row.findall(NS + "c"):
                        value = cell.find(NS + "v")
                        kind = cell.get("t")
                        if kind == "inlineStr":
                            inline = cell.find(NS + "is")
                            text = "".join(node.text or "" for node in inline.iter(NS + "t")) if inline is not None else ""
                        elif value is not None:
                            text = value.text or ""
                            if kind == "s":
                                try:
                                    index = int(text)
                                    if index < 0:
                                        raise ValueError()
                                    text = shared[index]
                                except (ValueError, IndexError) as exc:
                                    raise ValueError("Excel 文字索引损坏，请另存为 .xlsx 后上传。") from exc
                            elif kind == "b":
                                text = "是" if text == "1" else "否"
                        else:
                            text = ""
                        if cell.find(NS + "f") is not None and not text:
                            text = "（公式无已保存结果，请在 Excel 中计算并保存后重新上传）"
                        if text.strip():
                            col = cell_column(cell.get("r")) if cell.get("r") else next_column
                            if col > MAX_COLUMNS:
                                raise ValueError("表格超过 256 列，请只保留与创作有关的列后上传。")
                            values[col] = text
                            next_column = col + 1
                    line = format_row(row.get("r", ordinal), values)
                    if line:
                        count += 1
                        if not result.add(line):
                            return result.text()
            return result.text() if count else ""
    except (zipfile.BadZipFile, ET.ParseError, KeyError, RuntimeError, OSError) as exc:
        raise ValueError("这份 Excel 无法读取，请另存为未加密的 .xlsx 或 CSV 后上传。") from exc


def read_table(name, raw, limit=40000):
    suffix = posixpath.splitext(name.lower())[1]
    if suffix == ".xlsx":
        return read_xlsx(raw, limit)
    if suffix in {".csv", ".tsv"}:
        return read_delimited(raw, suffix, limit)
    raise ValueError("请使用 .xlsx、.csv 或 .tsv；旧版 .xls 请另存为 .xlsx。")
