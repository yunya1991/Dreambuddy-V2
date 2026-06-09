// Type declarations for FlexSearch
declare module 'flexsearch' {
  interface DocumentOptions<T = any> {
    tokenize?: 'strict' | 'forward' | 'reverse' | 'full';
    cache?: boolean;
    document?: {
      id: string;
      index?: string[];
      store?: string[];
    };
  }

  interface SearchOptions {
    limit?: number;
    enrich?: boolean;
    suggest?: boolean;
  }

  interface SearchResult<T = any> {
    field: string;
    result: T[];
  }

  class Document<T = any> {
    constructor(options?: DocumentOptions<T>);
    add(doc: T): void;
    search(query: string, options?: SearchOptions): SearchResult[];
    searchAsync(query: string, options?: SearchOptions): Promise<SearchResult[]>;
    remove(id: string | number): void;
    clear(): void;
  }

  export { Document, DocumentOptions, SearchOptions, SearchResult };
  export default { Document };
}
