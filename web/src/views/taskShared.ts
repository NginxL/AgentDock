import type { DockState, Mutate, Translate } from "../types";
export function taskLabel(status: string, t: Translate) {
  const labels: Record<string, [string, string]> = {
    draft: ["待开始", "Draft"],
    active: ["进行中", "In progress"],
    waiting_input: ["待你确认", "Needs your input"],
    review: ["待验收", "Ready for acceptance"],
    completed: ["已完成", "Completed"],
    interrupted: ["执行中断", "Interrupted"],
    paused: ["已暂停", "Paused"],
    cancelled: ["已取消", "Cancelled"],
    archived: ["已归档", "Archived"],
    recorded: ["已记录", "Recorded"],
    queued: ["已排队", "Queued"],
    pending: ["正在送达", "Sending"],
    accepted: ["已送达", "Delivered"],
    processed: ["本轮已结束", "Turn ended"],
    rejected: ["未送达", "Rejected"],
    unknown: ["送达待核实", "Delivery unknown"],
  };
  return labels[status] ? t(...labels[status]) : status;
}
export type Common = {
  state: DockState;
  t: Translate;
  busy: boolean;
  mutate: Mutate;
};
