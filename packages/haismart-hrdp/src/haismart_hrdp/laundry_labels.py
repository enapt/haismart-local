"""English labels for the 0504 twin washer + dryer's enum values, keyed on Haier's own descriptions.

Kept apart from the shared table in :mod:`haismart_hrdp.entity_spec` ON PURPOSE. A label there
renames that value on every appliance whose model uses the same words, which changes the state an
existing user's automation is keyed on. These are applied only to a device of class ``0504``, so
no other appliance's states move.

Two tables: one by description, and a few overrides by ``(attribute, description)`` where the same
words mean something different on another attribute of the same unit -- the shared programme list
calls programme 56 智慧洗 ("smart wash") on both drums, and the dryer's app shows it as "AI Dry".
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

__all__ = ["LAUNDRY_CLASSES", "laundry_label"]

#: Device classes these labels apply to.
LAUNDRY_CLASSES = frozenset({"0504"})

_BY_ATTRIBUTE: Mapping[tuple[str, str], str] = MappingProxyType({
    ("dryerUnifiedProgramSettings", "智慧洗"): "AI Dry",
    ("washerUnifiedProgramSettings", "智慧洗"): "AI Wash",
    ("washerMessage", "无"): "None",
})

_LABELS: Mapping[str, str] = MappingProxyType({
    # --- cycle phases ----------------------------------------------------------------------------
    "启动": "Running", "待机/未启动": "Standby", "待机状态": "Standby", "称重": "Weighing",
    "重量提示": "Load advice", "洗涤进水": "Wash fill", "洗涤加热": "Wash heating",
    "洗涤": "Washing", "洗涤排水": "Wash drain", "中间脱水": "Intermediate spin",
    "漂洗进水": "Rinse fill", "漂洗": "Rinsing", "漂洗排水": "Rinse drain",
    "最终脱水": "Final spin", "冷却": "Cooling down", "预约运行中": "Delayed start",
    "预约运行": "Delayed start", "洗衣程序运行完抖散中": "Tumbling after wash",
    "洗衣程序运行完烘干中": "Drying after wash", "洗衣程序运行完烘干结束": "Drying after wash finished",
    "洗衣程序运行完抖散结束": "Tumbling after wash finished", "护理中": "Care",
    "预洗进水": "Pre-wash fill", "预洗": "Pre-wash", "预洗加热": "Pre-wash heating",
    "预洗排水": "Pre-wash drain", "风干": "Air drying", "检测中": "Detecting",
    "冷风1": "Cool air 1", "冷风2": "Cool air 2", "加热1": "Heating 1", "加热2": "Heating 2",
    "程序结束": "Finished", "防皱": "Anti-crease", "自动判断负载中": "Sensing load",
    "预烘中": "Pre-drying", "保养中": "Maintenance",
    # --- end-of-cycle and other messages ---------------------------------------------------------
    "衣服已洗完": "Wash finished", "衣服已洗干": "Wash and dry finished",
    "衣服已烘干": "Drying finished", "无提示信息": "None", "熨烫提醒": "Ironing reminder",
    "请清理过滤器": "Clean the filter", "请清理水盒": "Empty the water box", "正在除菌": "Sterilising",
    "液体洗涤剂用完": "Detergent empty", "柔顺剂用完": "Softener empty", "消毒剂用完": "Disinfectant empty",
    "液体洗涤剂、柔顺剂用完": "Detergent and softener empty", "请关闭抽屉门": "Close the drawer",
    "筒内温度过高，不能开门": "Drum too hot to open", "筒内水位过高，不能开门": "Water too high to open",
    "排水过滤器需要清洗": "Clean the drain filter", "烘干过滤器需要清洗": "Clean the dryer filter",
    "门被打开，远程控制功能失效": "Door opened, remote control off",
    "架干燥使用说明": "Rack-dry instructions",
    "称重完成，请在分配器盒内加入适量洗衣粉": "Weighed, add powder detergent",
    "泡沫过多正进行消泡处理": "Too much foam, removing it",
    "负离子已完成": "Anion treatment done",
    "请使用筒自洁程序，进行筒内清洁": "Run a drum clean",
    "程序已运行达到指定周期,请清理排水过滤器": "Cycle count reached, clean the drain filter",
    "干洗叫单提醒": "Dry-cleaning reminder",
    "使用普通洗涤剂": "Use regular detergent", "使用浓缩洗涤剂": "Use concentrated detergent",
    "预留提示1": "Reserved message 1", "预留提示2": "Reserved message 2",
    # --- temperatures, levels and modes ----------------------------------------------------------
    "未设定": "Not set", "不设定": "Not set", "冷风": "Cool air",
    "低温": "Low temperature", "中温": "Medium temperature", "高温": "High temperature",
    "预留档位1": "Reserved 1", "预留档位2": "Reserved 2", "预留档位3": "Reserved 3",
    "不支持自动判干(定时类)": "Timed (no auto sensing)", "特低（即熨）": "Iron dry",
    "较低（即穿）": "Wear dry", "普通（储藏）": "Cupboard dry", "较高（特干）": "Extra dry",
    "特高": "Very dry",
    "正常烘干": "Normal drying", "节能烘干": "Eco drying", "快速烘干": "Fast drying",
    "强": "Strong", "弱": "Gentle", "不加热": "No heat", "性能": "Performance",
    "无烘干过程": "No drying", "强烘": "Strong dry", "弱烘": "Gentle dry", "智能烘干": "Smart dry",
    "30分钟烘干": "30 min dry", "60分钟烘干": "60 min dry", "90分钟烘干": "90 min dry",
    "120分钟烘干": "120 min dry", "150分钟烘干": "150 min dry", "180分钟烘干": "180 min dry",
    "210分钟烘干": "210 min dry",
    "标准(0%)": "Standard (0%)", "熨烫(12%)": "Iron (12%)", "衣架(3%)": "Hanger (3%)",
    "太阳(-3%)": "Sun (-3%)",
    "除皱": "De-wrinkle", "暖衣": "Warm clothes", "袪味": "Deodorise", "蓬松": "Fluff",
    "除潮": "Remove damp", "除醛": "Remove formaldehyde", "养护": "Care treatment",
    # --- detergent dispenser ---------------------------------------------------------------------
    "默认": "Default", "浓缩++": "Concentrated++", "浓缩+": "Concentrated+", "浓缩": "Concentrated",
    "普通": "Regular", "普通型": "Regular", "浓缩型": "Concentrated",
    "未放置": "Not fitted", "未知": "Unknown", "异常": "Error", "少": "Low",
    "精粹洗衣液": "Concentrated detergent", "净白助洗剂": "Whitening booster",
    "柔顺亮白剂": "Softening brightener", "亮色助洗剂": "Colour booster",
    "母婴精洗液": "Baby detergent",
    "不设定脏污度": "Not set", "自动测定脏污度，自动添加洗涤剂": "Auto",
    "轻度脏污，自动添加洗涤剂": "Light", "中度脏污，自动添加洗涤剂": "Medium",
    "重度脏污，自动添加洗涤剂": "Heavy",
    # --- programme families and where a programme came from --------------------------------------
    "不支持": "Not supported", "普通程序": "Standard programme", "空气洗类程序": "Air wash programme",
    "智能匀烘类程序": "Smart even-dry programme", "保养类程序": "Care programme",
    "护理": "Care", "洗烘": "Wash & dry", "洗护": "Wash & care", "烘护": "Dry & care",
    "洗烘护": "Wash, dry & care",
    "本机": "This machine", "语音模块": "Voice module", "音箱": "Smart speaker", "冰箱": "Fridge",
    # --- programmes (one shared list for both drums) ---------------------------------------------
    "空": "None", "棉麻": "Cotton", "化纤": "Synthetics", "羽绒": "Down", "窗帘": "Curtains",
    "混合": "Mixed", "衬衣": "Shirts", "童装": "Kids' wear", "轻柔": "Delicates",
    "烫烫净": "Hot clean", "羊毛": "Wool", "牛仔": "Denim", "空气洗": "Air wash",
    "筒自洁": "Drum clean", "内衣": "Underwear", "快洗15": "Quick 15", "快洗29": "Quick 29",
    "大件": "Bulky items", "运动服": "Sportswear", "摇篮柔洗": "Cradle gentle", "爱婴洗": "Baby care",
    "即时": "Instant", "真丝": "Silk", "记忆洗": "Memory", "护色洗": "Colour care",
    "手洗": "Hand wash", "毛巾": "Towels", "单脱水": "Spin only", "单烘干": "Dry only",
    "除毛洗": "Pet hair removal", "床单": "Bed sheets", "户外服": "Outdoor wear", "夜洗": "Night wash",
    "架干燥": "Rack dry", "抖散": "Loosen", "护肤洗": "Skin care", "消毒洗": "Sanitise",
    "高端专属": "Premium", "棉麻快洗": "Quick cotton", "加强洗": "Intensive", "熨烫": "Easy iron",
    "小太阳": "Little sun", "定时烘干": "Timed dry", "衣架烘干": "Hanger dry", "在线洗": "Online",
    "巨浪洗": "Wave wash", "CTTN棉麻": "CTTN cotton", "CTTN化纤": "CTTN synthetics",
    "防过敏": "Anti-allergy", "除异味": "Odour removal", "时间洗": "Timed wash",
    "冲锋衣": "Shell jacket", "App自诊断": "App self-diagnosis", "毛毯洗": "Blanket",
    "智慧洗": "AI wash", "智慧云洗": "AI cloud wash", "浴巾": "Bath towels",
    "紫外除菌": "UV sanitise", "蒸汽除螨": "Steam anti-mite", "巴氏杀菌": "Pasteurise",
    "超级空气洗": "Super air wash", "超级洗": "Super wash", "FPA快洗30": "FPA quick 30",
    "快洗烘": "Quick wash & dry", "美颜洗": "Beauty care", "棉麻20": "Cotton 20",
    "新欧标性能": "New EU performance", "欧标性能洗烘": "EU performance wash & dry",
    "香薰": "Aroma", "水雾清新": "Mist refresh", "貂皮": "Mink", "蚕丝被": "Silk quilt",
    "校服": "School uniform", "皮毛一体": "Shearling", "羊毛衫": "Wool sweater",
    "雪纺纱": "Chiffon", "西装": "Suits", "家纺": "Home textiles", "毛绒玩具": "Plush toys",
    "口罩": "Face masks", "快洗39": "Quick 39", "换季洗": "Seasonal", "欧标棉麻": "EU cotton",
    "欧标化纤": "EU synthetics", "混合2": "Mixed 2", "新衣洗2": "New clothes 2",
    "智慧洗烘": "AI wash & dry", "毛呢": "Tweed", "奢品家纺": "Luxury textiles",
    "筒洗烘": "Drum wash & dry", "亚麻": "Linen", "香护": "Fragrance care",
    "留香洗": "Lasting fragrance", "摇粒绒": "Fleece", "奢护": "Luxury care",
    "蒸汽智慧洗": "Steam AI wash", "衬衣蒸汽洗": "Shirt steam", "爱婴蒸汽洗": "Baby steam",
    "蒸汽防过敏": "Steam anti-allergy", "运动Bra": "Sports bra", "无感Bra": "Seamless bra",
    "塑形Bra": "Shaping bra", "蕾丝Bra": "Lace bra", "内裤": "Underpants",
    "蓝色消毒": "Blue sanitise", "隔离快净": "Quick isolation clean", "快速20": "Rapid 20",
    "快速30": "Rapid 30", "工作服": "Workwear", "尿布": "Nappies", "鞋子": "Shoes",
    "精细": "Fine", "休闲装": "Casual wear", "冷风30": "Cool air 30",
    "热风定时": "Timed warm air", "冷风定时": "Timed cool air", "羊毛大衣": "Wool coat",
    "婴童衣被": "Baby bedding", "纯棉婴儿装": "Cotton babywear", "棉质床品": "Cotton bedding",
    "亚麻西装": "Linen suit", "抓绒衣": "Polar fleece", "保养": "Care cycle",
    "皮革保养": "Leather care", "皮草保养": "Fur care", "织物靓色": "Colour refresh",
    "织物香护": "Fabric fragrance", "被子": "Duvet",
    # --- stains ----------------------------------------------------------------------------------
    "酒渍": "Wine", "草渍": "Grass", "泥土渍": "Mud", "血渍": "Blood", "奶渍": "Milk",
    "烹饪油": "Cooking oil", "茶渍": "Tea", "咖啡": "Coffee", "巧克力渍": "Chocolate",
    "唇彩": "Lipstick", "咖喱渍": "Curry", "奶茶": "Milk tea", "辣椒油": "Chilli oil",
    "蓝墨水": "Blue ink", "水彩笔": "Marker pen", "鞋油": "Shoe polish", "油画棒": "Oil pastel",
    "蓝莓": "Blueberry", "汗渍": "Sweat", "蛋渍": "Egg", "番茄酱": "Ketchup",
    "婴儿食物": "Baby food", "酱油渍": "Soy sauce", "豆瓣酱": "Bean paste", "辣椒酱": "Chilli sauce",
    "果渍": "Fruit",
})


def laundry_label(device_class: str | None, attribute: str, description: str) -> str | None:
    """The English label for ``description`` on a laundry appliance, or ``None`` if it has none."""
    if device_class not in LAUNDRY_CLASSES:
        return None
    text = description.strip()
    return _BY_ATTRIBUTE.get((attribute, text)) or _LABELS.get(text)
