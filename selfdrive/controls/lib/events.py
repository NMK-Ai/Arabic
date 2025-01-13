import os
from enum import IntEnum
from typing import Dict, Union, Callable, List, Optional

import linecache

from cereal import log, car
import cereal.messaging as messaging
from common.realtime import DT_CTRL
from common.conversions import Conversions as CV
from selfdrive.locationd.calibrationd import MIN_SPEED_FILTER

from common.params import Params

AlertSize = log.ControlsState.AlertSize
AlertStatus = log.ControlsState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
EventName = car.CarEvent.EventName


# أولويات التنبيهات
class Priority(IntEnum):
  LOWEST = 0
  LOWER = 1
  LOW = 2
  MID = 3
  HIGH = 4
  HIGHEST = 5


# أنواع الأحداث
class ET:
  ENABLE = 'enable'
  PRE_ENABLE = 'preEnable'
  NO_ENTRY = 'noEntry'
  WARNING = 'warning'
  USER_DISABLE = 'userDisable'
  SOFT_DISABLE = 'softDisable'
  IMMEDIATE_DISABLE = 'immediateDisable'
  PERMANENT = 'permanent'


# الحصول على اسم الحدث من التعداد (enum)
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}

try:
  LANG_FILE='/data/openpilot/selfdrive/assets/addon/lang/events/' + Params().get("LanguageSetting", encoding="utf8") + '.txt'
except:
  LANG_FILE='/data/openpilot/selfdrive/assets/addon/lang/events/main_en.txt'
  pass

# opkr
def tr(line_num: int):
  return linecache.getline(LANG_FILE, line_num)

class Events:
  def __init__(self):
    self.events: List[int] = []
    self.static_events: List[int] = []
    self.events_prev = dict.fromkeys(EVENTS.keys(), 0)

  @property
  def names(self) -> List[int]:
    return self.events

  def __len__(self) -> int:
    return len(self.events)

  def add(self, event_name: int, static: bool=False) -> None:
    if static:
      self.static_events.append(event_name)
    self.events.append(event_name)

  def clear(self) -> None:
    self.events_prev = {k: (v + 1 if k in self.events else 0) for k, v in self.events_prev.items()}
    self.events = self.static_events.copy()

  def any(self, event_type: str) -> bool:
    return any(event_type in EVENTS.get(e, {}) for e in self.events)

  def create_alerts(self, event_types: List[str], callback_args=None):
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = EVENTS[e].keys()
      for et in event_types:
        if et in types:
          alert = EVENTS[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if DT_CTRL * (self.events_prev[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{EVENT_NAME[e]}/{et}"
            alert.event_type = et
            ret.append(alert)
    return ret

  def add_from_msg(self, events):
    for e in events:
      self.events.append(e.name.raw)

  def to_msg(self):
    ret = []
    for event_name in self.events:
      event = car.CarEvent.new_message()
      event.name = event_name
      for event_type in EVENTS.get(event_name, {}):
        setattr(event, event_type, True)
      ret.append(event)
    return ret


class Alert:
  def __init__(self,
               alert_text_1: str,
               alert_text_2: str,
               alert_status: log.ControlsState.AlertStatus,
               alert_size: log.ControlsState.AlertSize,
               priority: Priority,
               visual_alert: car.CarControl.HUDControl.VisualAlert,
               audible_alert: car.CarControl.HUDControl.AudibleAlert,
               duration: float,
               alert_rate: float = 0.,
               creation_delay: float = 0.):

    self.alert_text_1 = alert_text_1
    self.alert_text_2 = alert_text_2
    self.alert_status = alert_status
    self.alert_size = alert_size
    self.priority = priority
    self.visual_alert = visual_alert
    self.audible_alert = audible_alert

    self.duration = int(duration / DT_CTRL)

    self.alert_rate = alert_rate
    self.creation_delay = creation_delay

    self.alert_type = ""
    self.event_type: Optional[str] = None

  def __str__(self) -> str:
    return f"{self.alert_text_1}/{self.alert_text_2} {self.priority} {self.visual_alert} {self.audible_alert}"

  def __gt__(self, alert2) -> bool:
    return self.priority > alert2.priority


class NoEntryAlert(Alert):
  def __init__(self, alert_text_2: str, visual_alert: car.CarControl.HUDControl.VisualAlert=VisualAlert.none):
    super().__init__(tr(1), alert_text_2, AlertStatus.normal,
                     AlertSize.mid, Priority.LOW, visual_alert,
                     AudibleAlert.refuse, 3.)


class SoftDisableAlert(Alert):
  def __init__(self, alert_text_2: str):
    super().__init__(tr(2), alert_text_2,
                     AlertStatus.userPrompt, AlertSize.full,
                     Priority.MID, VisualAlert.steerRequired,
                     AudibleAlert.warningSoft, 2.),


# less harsh version of SoftDisable, where the condition is user-triggered
class UserSoftDisableAlert(SoftDisableAlert):
  def __init__(self, alert_text_2: str):
    super().__init__(alert_text_2),
    self.alert_text_1 = tr(3)


class ImmediateDisableAlert(Alert):
  def __init__(self, alert_text_2: str):
    super().__init__(tr(4), alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.HIGHEST, VisualAlert.steerRequired,
                     AudibleAlert.warningImmediate, 4.),


class EngagementAlert(Alert):
  def __init__(self, audible_alert: car.CarControl.HUDControl.AudibleAlert):
    super().__init__("", "",
                     AlertStatus.normal, AlertSize.none,
                     Priority.MID, VisualAlert.none,
                     audible_alert, .2),


class NormalPermanentAlert(Alert):
  def __init__(self, alert_text_1: str, alert_text_2: str = "", duration: float = 0.2, priority: Priority = Priority.LOWER, creation_delay: float = 0.):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.normal, AlertSize.mid if len(alert_text_2) else AlertSize.small,
                     priority, VisualAlert.none, AudibleAlert.none, duration, creation_delay=creation_delay),


class StartupAlert(Alert):
  def __init__(self, alert_text_1: str, alert_text_2: str = tr(5), alert_status=AlertStatus.normal):
    super().__init__(alert_text_1, alert_text_2,
                     alert_status, AlertSize.mid,
                     Priority.LOWER, VisualAlert.none, AudibleAlert.none, 10.),


# ********** وظائف مساعدة **********
def get_display_speed(speed_ms: float, metric: bool) -> str:
  السرعة = int(round(speed_ms * (CV.MS_TO_KPH إذا كانت الوحدات متريّة else CV.MS_TO_MPH)))
  الوحدة = 'كم/س' إذا كانت متريّة else 'ميل/س'
  return f"{السرعة} {الوحدة}"


# ********** alert callback functions **********

AlertCallbackType = Callable[[car.CarParams, messaging.SubMaster, bool, int], Alert]


def soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  def func(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return SoftDisableAlert(alert_text_2)
  return func

def user_soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  def func(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return UserSoftDisableAlert(alert_text_2)
  return func


def below_engage_speed_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return NoEntryAlert(f"السرعة أقل من {get_display_speed(CP.minEnableSpeed, metric)}")


def below_steer_speed_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return Alert(
    f"التوجيه غير متوفر عندما تكون السرعة أقل من {get_display_speed(CP.minSteerSpeed, metric)}",
    "",
    AlertStatus.userPrompt, AlertSize.small,
    Priority.MID, VisualAlert.none, AudibleAlert.prompt, 0.4)


def calibration_incomplete_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return Alert(
    f"المعايرة جارية: %d%%" % sm['liveCalibration'].calPerc,
    f"قد السيارة بسرعة أكبر من {get_display_speed(MIN_SPEED_FILTER, metric)}",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2)


def no_gps_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  gps_integrated = sm['peripheralState'].pandaType in (log.PandaState.PandaType.uno, log.PandaState.PandaType.dos)
  return Alert(
    tr(10),  # ترجمة النصوص المرتبطة بالتنبيهات رقم 10
    tr(11) if gps_integrated else tr(12),  # النصوص الخاصة بوضع GPS حسب النوع
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWER, VisualAlert.none, AudibleAlert.none, .2, creation_delay=300.)


def wrong_car_mode_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  text = tr(13)  # النص الأساسي للوضعية غير الصحيحة للسيارة
  if CP.carName == "honda":
    text = tr(14)  # نص خاص بسيارات هوندا
  return NoEntryAlert(text)


def joystick_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  axes = sm['testJoystick'].axes
  gb, steer = list(axes)[:2] if len(axes) else (0., 0.)
  vals = f"الوقود: {round(gb * 100.)}%, التوجيه: {round(steer * 100.)}%"
  return NormalPermanentAlert("وضعية عصا التحكم (Joystick Mode)", vals)


# opkr
def can_error_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  if os.path.isfile('/data/log/can_missing.txt'):
    f = open('/data/log/can_missing.txt', 'r')
    add = f.readline()
    add_int = int(add, 0)
    f.close()
    return Alert(
      f"خطأ في CAN: العنصر {add} مفقود\n القيمة العشرية: {add_int}",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.)
  elif os.path.isfile('/data/log/can_timeout.txt'):
    f = open('/data/log/can_timeout.txt', 'r')
    add = f.readline()
    add_int = int(add, 0)
    f.close()
    return Alert(
      f"خطأ في CAN: العنصر {add} تجاوز الوقت المسموح\n القيمة العشرية: {add_int}",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.)
  else:
    return Alert(
      "خطأ في CAN: تحقق من توصيلات الأسلاك (Harness)",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.)


EVENTS: Dict[int, Dict[str, Union[Alert, AlertCallbackType]]] = {
  # ********** events with no alerts **********

  EventName.stockFcw: {},

  # ********** events only containing alerts displayed in all states **********

  EventName.joystickDebug: {
    ET.WARNING: joystick_alert,
    ET.PERMANENT: NormalPermanentAlert(tr(21)),
  },

  EventName.controlsInitializing: {
    ET.NO_ENTRY: NoEntryAlert(tr(22)),
  },

  EventName.startup: {
    ET.PERMANENT: StartupAlert(tr(23))
  },

  EventName.startupMaster: {
    ET.PERMANENT: StartupAlert(tr(24),
                               alert_status=AlertStatus.userPrompt),
  },

  # Car is recognized, but marked as dashcam only
  EventName.startupNoControl: {
    ET.PERMANENT: StartupAlert(tr(25)),
  },

  # Car is not recognized
  EventName.startupNoCar: {
    ET.PERMANENT: StartupAlert(tr(26)),
  },

  EventName.startupNoFw: {
    ET.PERMANENT: StartupAlert(tr(27),
                               tr(28),
                               alert_status=AlertStatus.userPrompt),
  },

  EventName.dashcamMode: {
    ET.PERMANENT: NormalPermanentAlert(tr(29),
                                       priority=Priority.LOWEST),
  },

  EventName.invalidLkasSetting: {
    ET.PERMANENT: NormalPermanentAlert(tr(30),
                                       tr(31)),
  },

  EventName.cruiseMismatch: {
#ET.PERMANENT: تنبيه التعطيل الفوري ("فشل نظام القائد الآلي في إلغاء التحكم في السرعة"),
  },

# نظام القائد الآلي (NMK.AI) لا يتعرف على السيارة. يتم تحويل النظام إلى وضع القراءة فقط.
# يمكن حل هذه المشكلة عن طريق إضافة بصمة السيارة (Fingerprint).
# لمزيد من المعلومات، راجع الرابط: https://github.com/commaai/openpilot/wiki/Fingerprinting
  EventName.carUnrecognized: {
    ET.PERMANENT: NormalPermanentAlert(tr(32),
                                       tr(33),
                                       priority=Priority.LOWEST),
  },

  EventName.stockAeb: {
    ET.PERMANENT: Alert(
      tr(34),
      tr(35),
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 2.),
    ET.NO_ENTRY: NoEntryAlert(tr(36)),
  },

  EventName.fcw: {
    ET.PERMANENT: Alert(
      tr(37),
      tr(38),
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.warningSoft, 2.),
  },

  EventName.ldw: {
    ET.PERMANENT: Alert(
      tr(39),
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.ldw, AudibleAlert.prompt, 3.),
  },

# ********** أحداث تحتوي فقط على التنبيهات التي تظهر أثناء تفعيل النظام **********

  EventName.gasPressed: {
    ET.PRE_ENABLE: Alert(
      tr(40),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1, creation_delay=1.),
  },

# يحاول نظام القائد الآلي (NMK.AI) تعلم بعض المعايير الخاصة بسيارتك من خلال مراقبة
# كيفية استجابة السيارة لمدخلات التوجيه سواء من الإنسان أو من نظام القائد الآلي.
# هذه المعايير تشمل:
# - نسبة التوجيه: نسبة التروس في نظام التوجيه. زاوية التوجيه مقسومة على زاوية الإطارات.
# - صلابة الإطارات: مقدار التماسك الذي توفره الإطارات.
# - انحراف الزاوية: معظم مستشعرات زاوية التوجيه تحتوي على انحراف وتقيس زاوية غير صفرية عند القيادة في خط مستقيم.
# يتم عرض هذا التنبيه عندما تتجاوز أي من هذه القيم الحد المعقول. يمكن أن يحدث ذلك بسبب:
# - سوء في محاذاة السيارة (alignment).
# - بيانات خاطئة من المستشعرات.
# إذا تكرر هذا التنبيه بشكل منتظم، يُنصح بإنشاء تقرير على GitHub.
  EventName.vehicleModelInvalid: {
    ET.NO_ENTRY: NoEntryAlert(tr(41)),
    ET.SOFT_DISABLE: soft_disable_alert(tr(42)),
  },

  EventName.steerTempUnavailableSilent: {
    ET.WARNING: Alert(
      tr(43),
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.prompt, 1.),
  },

  EventName.preDriverDistracted: {
    ET.WARNING: Alert(
      tr(44),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.promptDriverDistracted: {
    ET.WARNING: Alert(
      tr(45),
      tr(46),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverDistracted: {
    ET.WARNING: Alert(
      tr(47),
      tr(48),
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.preDriverUnresponsive: {
    ET.WARNING: Alert(
      tr(49),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.promptDriverUnresponsive: {
    ET.WARNING: Alert(
      tr(50),
      tr(51),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverUnresponsive: {
    ET.WARNING: Alert(
      tr(52),
      tr(53),
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.manualRestart: {
    ET.WARNING: Alert(
      tr(54),
      tr(55),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.resumeRequired: {
    ET.WARNING: Alert(
      tr(56),
      tr(57),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.belowSteerSpeed: {
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.preLaneChangeLeft: {
    ET.WARNING: Alert(
      tr(58),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.preLaneChangeRight: {
    ET.WARNING: Alert(
      tr(59),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.laneChangeBlocked: {
    ET.WARNING: Alert(
      tr(60),
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
  },

  EventName.laneChange: {
    ET.WARNING: Alert(
      tr(61),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.e2eLongAlert: {
    ET.WARNING: Alert(
      tr(62),
      tr(63),
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 2.),
  },

  EventName.laneChangeManual: {
    ET.WARNING: Alert(
      tr(64),
      tr(65),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.emgButtonManual: {
    ET.WARNING: Alert(
      tr(66),
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.driverSteering: {
    ET.WARNING: Alert(
      tr(67),
      tr(68),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.steerSaturated: {
    ET.WARNING: Alert(
      tr(69),
      tr(70),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.prompt, 1.),
  },

# يتم إطلاق التنبيه عندما يتم تشغيل المروحة بأكثر من 50% ولكنها لا تدور
  EventName.fanMalfunction: {
    ET.PERMANENT: NormalPermanentAlert(tr(71), tr(72)),
},

# يتم إطلاق التنبيه عندما لا تقوم الكاميرا بإخراج الإطارات بمعدل إطار ثابت
  EventName.cameraMalfunction: {
    ET.PERMANENT: NormalPermanentAlert(tr(73), tr(74)),
},

# غير مستخدم
  EventName.gpsMalfunction: {
    ET.PERMANENT: NormalPermanentAlert(tr(75), tr(76)),
},

# عندما يكون هناك اختلاف بين موقع GPS والموقع المحلي (localizer)،
# يتم إعادة تعيين الموقع المحلي إلى موقع GPS الحالي. يتم إطلاق هذا
# التنبيه عندما يتم إعادة التعيين أكثر من المتوقع.
  EventName.localizerMalfunction: {
    ET.PERMANENT: NormalPermanentAlert(tr(77), tr(78)),
  },

  EventName.modeChangeOpenpilot: {
    ET.WARNING: Alert(
      tr(79),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 1.),
  },
  
  EventName.modeChangeDistcurv: {
    ET.WARNING: Alert(
      tr(80),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 1.),
  },
  EventName.modeChangeDistance: {
    ET.WARNING: Alert(
      tr(81),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 1.),
  },
  EventName.modeChangeCurv: {
    ET.WARNING: Alert(
      tr(82),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 1.),
  },
  EventName.modeChangeOneway: {
    ET.WARNING: Alert(
      tr(83),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 1.),
  },
  EventName.modeChangeMaponly: {
    ET.WARNING: Alert(
      tr(84),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.warning, 1.),
  },
  EventName.needBrake: {
    ET.WARNING: Alert(
      tr(85),
      tr(86),
      AlertStatus.normal, AlertSize.full,
      Priority.LOW, VisualAlert.none, AudibleAlert.promptRepeat, .1),
  },
  EventName.routineDriveOn: {
    ET.WARNING: Alert(
      tr(87),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

# ********** الأحداث التي تؤثر على انتقال حالات التحكم **********

  EventName.pcmEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.buttonEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.pcmDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventName.buttonCancel: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventName.brakeHold: {
    ET.WARNING: Alert(
      tr(88),
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },

  EventName.parkBrake: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert(tr(89)),
  },

  EventName.pedalPressed: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert(tr(90),
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.wrongCarMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.wrongCruiseMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.none),
    ET.NO_ENTRY: NoEntryAlert(tr(91)),
  },

  EventName.steerTempUnavailable: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(92)),
    ET.NO_ENTRY: NoEntryAlert(tr(93)),
  },
  
  EventName.isgActive: {
    ET.WARNING: Alert(
      tr(94),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.camSpeedDown: {
    ET.WARNING: Alert(
      tr(95),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5, alert_rate=0.75),
  },

  EventName.standstillResButton: {
    ET.WARNING: Alert(
      tr(96),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5, alert_rate=0.75),
  },

  EventName.gapAdjusting: {
    ET.WARNING: Alert(
      tr(97),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5, alert_rate=0.75),
  },

  EventName.resCruise: {
    ET.WARNING: Alert(
      tr(98),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5),
  },

  EventName.curvSpeedDown: {
    ET.WARNING: Alert(
      tr(99),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5),
  },

  EventName.cutinDetection: {
    ET.WARNING: Alert(
      tr(100),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5),
  },

  EventName.outOfSpace: {
    ET.PERMANENT: NormalPermanentAlert(tr(101)),
    ET.NO_ENTRY: NoEntryAlert(tr(102)),
  },

  EventName.belowEngageSpeed: {
    ET.NO_ENTRY: below_engage_speed_alert,
  },

  EventName.sensorDataInvalid: {
    ET.PERMANENT: Alert(
      tr(103),
      tr(104),
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert(tr(105)),
  },

  EventName.noGps: {
    ET.PERMANENT: no_gps_alert,
  },

  EventName.soundsUnavailable: {
    ET.PERMANENT: NormalPermanentAlert(tr(106), tr(107)),
    ET.NO_ENTRY: NoEntryAlert(tr(108)),
  },

  EventName.tooDistracted: {
    ET.NO_ENTRY: NoEntryAlert(tr(109)),
  },

  EventName.overheat: {
    ET.PERMANENT: NormalPermanentAlert(tr(110)),
    ET.SOFT_DISABLE: soft_disable_alert(tr(111)),
    ET.NO_ENTRY: NoEntryAlert(tr(112)),
  },

  EventName.wrongGear: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert(tr(113)),
  },

# يتم عرض هذا التنبيه عندما تكون زوايا المعايرة خارج النطاق المقبول.
# على سبيل المثال، إذا كان الجهاز موجهًا كثيرًا إلى اليسار أو اليمين.
# عادةً لا يمكن حل هذه المشكلة إلا عن طريق إزالة الحامل من الزجاج الأمامي بالكامل،
# وإعادة تثبيته مع التأكد من أن الجهاز موجه مباشرة إلى الأمام وفي وضع مستوٍ.
# لمزيد من المعلومات، قم بزيارة الرابط: https://comma.ai/setup
  EventName.calibrationInvalid: {
    ET.PERMANENT: NormalPermanentAlert(tr(114), tr(115)),
    ET.SOFT_DISABLE: soft_disable_alert(tr(116)),
    ET.NO_ENTRY: NoEntryAlert(tr(117)),
  },

  EventName.calibrationIncomplete: {
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: soft_disable_alert(tr(118)),
    ET.NO_ENTRY: NoEntryAlert(tr(119)),
  },

  EventName.doorOpen: {
    ET.SOFT_DISABLE: user_soft_disable_alert(tr(120)),
    ET.NO_ENTRY: NoEntryAlert(tr(121)),
  },

  EventName.seatbeltNotLatched: {
    ET.SOFT_DISABLE: user_soft_disable_alert(tr(122)),
    ET.NO_ENTRY: NoEntryAlert(tr(123)),
  },

  EventName.espDisabled: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(124)),
    ET.NO_ENTRY: NoEntryAlert(tr(125)),
  },

  EventName.lowBattery: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(126)),
    ET.NO_ENTRY: NoEntryAlert(tr(127)),
  },

# تتواصل خدمات القائد الآلي (openpilot) المختلفة مع بعضها البعض بفواصل زمنية محددة.
# إذا لم يتم الالتزام بالجدول الزمني المنتظم للتواصل، يتم عرض هذا التنبيه.
# قد يشير ذلك إلى أن إحدى الخدمات قد تعطلت، أو لم ترسل رسالة لعشر مرات ضعف الفاصل الزمني المنتظم،
# أو أن المتوسط الزمني للفواصل قد زاد بأكثر من 10% عن المتوقع.
  EventName.commIssue: {
    ET.WARNING: Alert(
      tr(128),
      tr(129),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1.),
  },
  
  EventName.commIssueAvgFreq: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(130)),
    ET.NO_ENTRY: NoEntryAlert(tr(131)),
  },  

# يتم عرض هذا التنبيه عندما يكتشف مدير النظام أن إحدى الخدمات توقفت بشكل غير متوقع أثناء القيادة
  EventName.processNotRunning: {
    ET.NO_ENTRY: NoEntryAlert(tr(132)),
  },

  EventName.radarFault: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(133)),
    ET.NO_ENTRY: NoEntryAlert(tr(134)),
  },

# يجب أن تتم معالجة كل إطار من الكاميرا بواسطة النموذج (modeld). إذا لم يتمكن النموذج
# من معالجة الإطارات بسرعة كافية، يجب تجاهلها. يتم عرض هذا التنبيه عندما يتم
# تجاهل أكثر من 20% من الإطارات.
  EventName.modeldLagging: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(135)),
    ET.NO_ENTRY: NoEntryAlert(tr(136)),
  },

# بالإضافة إلى التنبؤ بالمسار وخطوط الحارات وبيانات السيارة الأمامية، يقوم النموذج
# أيضًا بالتنبؤ بالسرعة الحالية وسرعة الدوران للسيارة. إذا كان النموذج
# غير واثق بدرجة كبيرة من السرعة الحالية أثناء حركة السيارة، فإن ذلك
# يعني عادةً أن النموذج يواجه صعوبة في فهم المشهد. يتم استخدام هذه الحالة
# كآلية استدلالية لتحذير السائق.
  EventName.posenetInvalid: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(137)),
    ET.NO_ENTRY: NoEntryAlert(tr(138)),
  },

# عندما يكتشف محدد الموقع (localizer) تسارعًا يزيد عن 40 م/ث^2 (~4G)،
# يتم تنبيه السائق بأن الجهاز قد يكون قد سقط من الزجاج الأمامي.
  EventName.deviceFalling: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(139)),
    ET.NO_ENTRY: NoEntryAlert(tr(140)),
  },

  EventName.lowMemory: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(141)),
    ET.PERMANENT: NormalPermanentAlert(tr(142), tr(143)),
    ET.NO_ENTRY: NoEntryAlert(tr(144)),
  },

  EventName.highCpuUsage: {
#ET.SOFT_DISABLE: تنبيه تعطيل مؤقت ("خلل في النظام: أعد تشغيل جهازك"),
#ET.PERMANENT: تنبيه دائم ("خلل في النظام", "أعد تشغيل جهازك"),
    ET.NO_ENTRY: NoEntryAlert(tr(145)),
  },

  EventName.accFaulted: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(146)),
    ET.PERMANENT: NormalPermanentAlert(tr(147), ""),
    ET.NO_ENTRY: NoEntryAlert(tr(148)),
  },

  EventName.controlsMismatch: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(149)),
  },

  EventName.roadCameraError: {
    ET.PERMANENT: NormalPermanentAlert(tr(150),
                                       duration=1.,
                                       creation_delay=30.),
  },

  EventName.driverCameraError: {
    ET.PERMANENT: NormalPermanentAlert(tr(151),
                                       duration=1.,
                                       creation_delay=30.),
  },

  EventName.wideRoadCameraError: {
    ET.PERMANENT: NormalPermanentAlert(tr(152),
                                       duration=1.,
                                       creation_delay=30.),
  },

# أحيانًا قد يواجه نظام USB على الجهاز حالة سيئة
# مما يتسبب في فقدان الاتصال بجهاز الباندا.
  EventName.usbError: {
    ET.SOFT_DISABLE: soft_disable_alert(tr(153)),
    ET.PERMANENT: NormalPermanentAlert(tr(154), ""),
    ET.NO_ENTRY: NoEntryAlert(tr(155)),
  },

# يمكن إصدار هذا التنبيه للأسباب التالية:
# - لم يتم استقبال أي بيانات CAN على الإطلاق.
# - يتم استقبال بيانات CAN، ولكن بعض الرسائل لا تصل بالتردد الصحيح.
# إذا كنت لا تعمل على إنشاء منفذ جديد لسيارة، فعادةً ما يكون السبب هو أسلاك معطوبة.
  EventName.canError: {
    ET.PERMANENT: can_error_alert,
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(156)),
    # ET.PERMANENT: Alert(
    #   "CAN Error: Check Connections",
    #   "",
    #   AlertStatus.normal, AlertSize.small,
    #   Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert(tr(157)),
  },

  EventName.steerUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(158)),
    ET.PERMANENT: NormalPermanentAlert(tr(159)),
    ET.NO_ENTRY: NoEntryAlert(tr(160)),
  },

  EventName.brakeUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(161)),
    ET.PERMANENT: NormalPermanentAlert(tr(162)),
    ET.NO_ENTRY: NoEntryAlert(tr(163)),
  },

  EventName.reverseGear: {
    ET.PERMANENT: Alert(
      tr(164),
      "",
      AlertStatus.userPrompt, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    # ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Reverse Gear"),
    ET.NO_ENTRY: NoEntryAlert(tr(165)),
  },

  EventName.gearNotD: {
    ET.WARNING: Alert(
      tr(166),
      "",
      AlertStatus.userPrompt, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    # ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Reverse Gear"),
    ET.NO_ENTRY: NoEntryAlert(tr(167)),
  },

# في السيارات التي تستخدم نظام تثبيت السرعة التكيفي (ACC) المدمج من المصنع،
# قد تقرر السيارة إلغاء تفعيل نظام ACC لأسباب مختلفة.
# عندما يحدث ذلك، لا يمكن للنظام التحكم بالسيارة بعد الآن، لذلك يجب تحذير المستخدم فورًا.
  EventName.cruiseDisabled: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(168)),
  },

# لتخطيط مسار القيادة يتم استخدام التحكم التنبؤي النموذجي (MPC).
# وهو عبارة عن خوارزمية تحسين لا تضمن دائمًا إيجاد حل ممكن.
# إذا لم يتم العثور على حل أو إذا كان الحل ذا تكلفة عالية جدًا، يتم عرض هذا التنبيه.
  EventName.plannerError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(169)),
    ET.NO_ENTRY: NoEntryAlert(tr(170)),
  },

# عندما يفتح المرحل (relay) في صندوق التوصيلات، يتم فصل ناقل CAN بين كاميرا LKAS
# وبقية أجزاء السيارة. إذا تم استقبال رسائل من كاميرا LKAS على جانب السيارة،
# فهذا يعني عادةً أن المرحل لم يفتح بشكل صحيح، ويتم عرض هذا التنبيه.
  EventName.relayMalfunction: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert(tr(171)),
    ET.PERMANENT: NormalPermanentAlert(tr(172), tr(173)),
    ET.NO_ENTRY: NoEntryAlert(tr(174)),
  },

  EventName.noTarget: {
    ET.IMMEDIATE_DISABLE: Alert(
      tr(175),
      tr(176),
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.none, 3.),
    ET.NO_ENTRY: NoEntryAlert(tr(177)),
  },

  EventName.speedTooLow: {
    ET.IMMEDIATE_DISABLE: Alert(
      tr(178),
      tr(179),
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.none, 3.),
  },

# عندما تسير السيارة بسرعة أعلى من معظم السيارات في بيانات التدريب، قد تكون مخرجات النموذج غير متوقعة.
  EventName.speedTooHigh: {
    ET.WARNING: Alert(
      tr(180),
      tr(181),
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 4.),
    ET.NO_ENTRY: NoEntryAlert(tr(182)),
  },

  EventName.lowSpeedLockout: {
    ET.PERMANENT: NormalPermanentAlert(tr(183)),
    ET.NO_ENTRY: NoEntryAlert(tr(184)),
  },

  EventName.lkasDisabled: {
# ET.PERMANENT: تنبيه دائم عادي ("تم تعطيل LKAS: قم بتفعيل LKAS للتشغيل"),
# ET.NO_ENTRY: تنبيه عدم دخول ("تم تعطيل LKAS"),
    ET.WARNING: Alert(
      tr(185),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.disengage, 1., alert_rate=0.5),
  },

  EventName.lkasEnabled: {
# ET.PERMANENT: تنبيه دائم عادي ("تم تعطيل نظام المساعدة في الحفاظ على المسار (LKAS): قم بتفعيله للتشغيل"),
# ET.NO_ENTRY: تنبيه منع الدخول ("تم تعطيل نظام المساعدة في الحفاظ على المسار (LKAS)"),
    ET.WARNING: Alert(
      tr(186),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.engage, 1.),
  },
 
  EventName.unSleepMode: {
    ET.WARNING: Alert(
      tr(187),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 2.),
  },

  EventName.speedBump: {
    ET.WARNING: Alert(
      tr(188),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5),
  },

  EventName.sccDriverOverride: {
    ET.WARNING: Alert(
      tr(189),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .5),
  },

  EventName.doNotDisturb: {
    ET.WARNING: Alert(
      tr(190),
      tr(191),
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 5.),
  },

  EventName.chimeAtResume: {
    ET.WARNING: Alert(
      tr(192),
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.dingdong, 3.),
  },

}
