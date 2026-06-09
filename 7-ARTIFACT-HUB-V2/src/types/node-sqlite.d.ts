declare module "node:sqlite" {
  export interface StatementSync {
    run(...params: any[]): void;
    all(...params: any[]): any[];
    get(...params: any[]): any;
  }

  export class DatabaseSync {
    constructor(filename: string);
    exec(sql: string): void;
    prepare(sql: string): StatementSync;
  }
}

