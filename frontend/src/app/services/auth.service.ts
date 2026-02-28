import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, tap, catchError, of } from 'rxjs';
import { Router } from '@angular/router';

export interface LoginResponse {
    message: string;
    username: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
    private apiUrl = '/api/auth';
    private _isAuthenticated = new BehaviorSubject<boolean>(false);
    private _username = new BehaviorSubject<string>('');

    isAuthenticated$ = this._isAuthenticated.asObservable();
    username$ = this._username.asObservable();

    constructor(private http: HttpClient, private router: Router) { }

    checkAuth(): Observable<any> {
        return this.http.get<any>(`${this.apiUrl}/me`).pipe(
            tap(res => {
                this._isAuthenticated.next(true);
                this._username.next(res.username);
            }),
            catchError(() => {
                this._isAuthenticated.next(false);
                this._username.next('');
                return of(null);
            })
        );
    }

    login(username: string, password: string): Observable<LoginResponse> {
        return this.http.post<LoginResponse>(`${this.apiUrl}/login`, { username, password }).pipe(
            tap(res => {
                this._isAuthenticated.next(true);
                this._username.next(res.username);
            })
        );
    }

    logout(): Observable<any> {
        return this.http.post(`${this.apiUrl}/logout`, {}).pipe(
            tap(() => {
                this._isAuthenticated.next(false);
                this._username.next('');
                this.router.navigate(['/login']);
            })
        );
    }

    get isLoggedIn(): boolean {
        return this._isAuthenticated.value;
    }
}
