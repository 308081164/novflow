import { ApiError, isLicenseError, isLicenseExpired } from "../api";

export type ErrorModalState = {
  open: boolean;
  title: string;
  message: string;
  settingsLink: boolean;
};

export const closedErrorModal: ErrorModalState = {
  open: false,
  title: "",
  message: "",
  settingsLink: false,
};

export function errorModalFromUnknown(error: unknown, fallbackTitle = "操作失败"): ErrorModalState {
  if (isLicenseError(error)) {
    const expired = isLicenseExpired(error);
    return {
      open: true,
      title: expired ? "授权已过期" : "需要授权激活",
      message: error instanceof ApiError && error.message
        ? error.message
        : "授权已过期，请前往设置完成激活",
      settingsLink: true,
    };
  }
  if (error instanceof ApiError) {
    return {
      open: true,
      title: fallbackTitle,
      message: error.message || fallbackTitle,
      settingsLink: false,
    };
  }
  if (error instanceof Error) {
    return {
      open: true,
      title: fallbackTitle,
      message: error.message || fallbackTitle,
      settingsLink: false,
    };
  }
  return {
    open: true,
    title: fallbackTitle,
    message: String(error),
    settingsLink: false,
  };
}
