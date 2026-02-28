import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, tap } from 'rxjs';

export interface ScriptStatusResponse {
    running: boolean;
    script_type: string | null;
    started_at: string | null;
    finished_at: string | null;
    exit_code: number | null;
    error: string | null;
}

@Injectable({ providedIn: 'root' })
export class ScriptService {
    private apiUrl = '/api/script';
    private _status = new BehaviorSubject<ScriptStatusResponse | null>(null);

    status$ = this._status.asObservable();

    constructor(private http: HttpClient) { }

    runScript(scriptType: 'collect' | 'score' = 'collect'): Observable<any> {
        return this.http.post(`${this.apiUrl}/run`, { script_type: scriptType }).pipe(
            tap(() => this.pollStatus())
        );
    }

    getStatus(): Observable<ScriptStatusResponse> {
        return this.http.get<ScriptStatusResponse>(`${this.apiUrl}/status`).pipe(
            tap(status => this._status.next(status))
        );
    }

    pollStatus(): void {
        const interval = setInterval(() => {
            this.getStatus().subscribe({
                next: (status) => {
                    if (!status.running) {
                        clearInterval(interval);
                    }
                },
                error: () => clearInterval(interval)
            });
        }, 3000);
    }
}
