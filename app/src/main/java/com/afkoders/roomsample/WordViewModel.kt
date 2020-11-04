package com.afkoders.roomsample

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.viewModelScope
import com.afkoders.roomsample.repository.Word
import com.afkoders.roomsample.repository.WordDatabase
import com.afkoders.roomsample.repository.WordRepository
import kotlinx.coroutines.launch

/**
 * Created by Kalevych Oleksandr on 18.10.2020.
 */

class WordViewModel (application: Application): AndroidViewModel(application){
    val repository: WordRepository

    val allWords: LiveData<List<Word>>


    init {
        val wordsDao = WordDatabase.getDatabase(application, viewModelScope).wordDao()
        repository = WordRepository(wordsDao)
        allWords =  repository.allWords
    }

    fun insert(word: Word){
        viewModelScope.launch {
            repository.insert(word)
        }
    }
}