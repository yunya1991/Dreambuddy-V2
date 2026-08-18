export interface RechargeNavigator {
  push(path: string): void;
}

export function navigateToRecharge(router: RechargeNavigator) {
  router.push("/recharge");
}
